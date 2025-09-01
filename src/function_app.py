import azure.functions as func         # Azure Functions Python SDK (decorators, trigger types)
import logging                         # Standard logging module for diagnostics
import base64                          # For Base64 decoding of incoming payloads
import gzip                            # For gzip decompression attempts
import io                              # In-memory byte buffers
import re                              # Regular expressions (sanitization, base64 cleanup)
import json                            # JSON parsing/serialization
import os                              # Access environment variables (app settings)
from datetime import datetime          # Timestamps for file naming
from zlib import decompress            # zlib decompression (raw & header variants)
import pyarrow as pa                   # Apache Arrow in-memory data structures
import pyarrow.parquet as pq           # Parquet writer
from azure.storage.blob import BlobServiceClient  # Azure Blob SDK client

# Single FunctionApp instance required by the v2 programming model
app = func.FunctionApp()

# Regex to keep only safe characters when reading the "Source" (e.g., "db.table")
_NAME_KEEP = re.compile(r'[^a-zA-Z0-9._-]')

# =============================================================================
# Env helpers (no in-code defaults)
# =============================================================================
def _req(name: str) -> str:
    v = os.getenv(name)                                                   # Read env var (Function App setting)
    if v is None or (isinstance(v, str) and v.strip() == ""):             # Fail fast if missing/blank
        raise RuntimeError(f"Missing required app setting: {name}")
    return v                                                               # Return the non-empty value

def _req_int(name: str) -> int:
    return int(_req(name))                                                # Same as _req but cast to int

def _req_bool(name: str) -> bool:
    return _req(name).strip().lower() in ("1", "true", "yes", "y")        # Accept several truthy strings

def _opt(name: str) -> str | None:
    v = os.getenv(name)                                                   # Optional env var
    return v if v is not None and v.strip() != "" else None               # Normalize to None if empty

# =============================================================================
# Validate required settings up-front (fail fast)
# =============================================================================
# Storage
_ = _req("AzureWebJobsStorage")                                           # Must exist; also used by Blob SDK
_ = _req("OUTPUT_CONTAINER")                                              # Target container name (required)

# Behavior toggles / parameters
MAX_BATCH_SIZE        = _req_int("MAX_BATCH_SIZE")                        # Max rows per Parquet chunk
PARQUET_COMPRESSION   = _req("PARQUET_COMPRESSION")                       # Parquet compression (e.g., SNAPPY)
DESTINATION_FALLBACK  = _req("DESTINATION_FALLBACK")                      # Folder when 'Destination' missing
WRITE_DECODED_ONLY    = _req_bool("WRITE_DECODED_ONLY")                   # Toggle (kept for future use)
LOG_LEVEL             = _req("LOG_LEVEL").upper()                         # Logging level (INFO/DEBUG/etc.)

# Optional prefix path inside container (virtual subfolders)
OUTPUT_PREFIX         = _opt("OUTPUT_PREFIX")

# Apply log level globally for the Function App
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# =============================================================================
# Storage helpers
# =============================================================================
def initialize_blob_client() -> BlobServiceClient:
    try:
        return BlobServiceClient.from_connection_string(_req("AzureWebJobsStorage"))  # Create Blob client
    except Exception as e:
        logging.error(f"Blob storage initialization failed: {e}")        # Log and bubble up
        raise

def ensure_target_container(blob_service_client: BlobServiceClient):
    try:
        container_client = blob_service_client.get_container_client(_req("OUTPUT_CONTAINER"))  # Get container client
        if not container_client.exists():                                   # Create if it doesn't exist
            container_client.create_container()
            logging.info(f"Created container: {_req('OUTPUT_CONTAINER')}")
        return container_client                                             # Return for possible further use
    except Exception as e:
        logging.error(f"Failed to ensure container {_req('OUTPUT_CONTAINER')}: {e}")  # Log error
        raise

def _join_path(*parts: str) -> str:
    clean = [p.strip("/ ") for p in parts if p and p.strip("/ ")]          # Trim slashes/spaces and drop empties
    return "/".join(clean)                                                 # Join as virtual path (blob prefix)

# =============================================================================
# Name sanitization
# =============================================================================
def _sanitize_folder(name: str) -> str:
    return re.sub(r'[^a-z0-9_-]+', '_', (name or '').strip().lower())     # Lowercase + allow only a-z0-9_-

def _sanitize_table(name: str) -> str:
    return re.sub(r'[^a-z0-9_-]+', '_', (name or '').strip().lower())     # Same rule for table/file stem

# =============================================================================
# Folder / table resolution (no defaults here; uses env var for fallback)
# =============================================================================
def resolve_folder_and_table(message: dict) -> tuple[str, str, str]:
    source = str(message.get("Source", "")).strip()                        # Read raw 'Source' from message
    source = _NAME_KEEP.sub("", source)                                    # Keep only safe chars (db.table)

    if '.' in source:                                                      # If "db.table" pattern
        db_part, table_part = source.split('.', 1)                         # Split into db and table
    else:
        db_part, table_part = source, source                               # No dot → both equal to source

    raw_destination = str(message.get("Destination") or "").strip()        # Preferred folder if present
    folder_source = raw_destination if raw_destination else DESTINATION_FALLBACK  # Else fallback from env

    folder     = _sanitize_folder(folder_source or DESTINATION_FALLBACK)   # Sanitize folder for path
    source_db  = _sanitize_folder(db_part or "unknown_db")                 # Sanitize db name (metadata only)
    table_name = _sanitize_table(table_part or "unknown_table")            # Sanitize table/file stem

    return folder, source_db, table_name                                   # Return routing tuple

# =============================================================================
# Decode / Decompress helpers
# =============================================================================
def clean_base64(data: str) -> str:
    try:
        cleaned = re.sub(r'[^A-Za-z0-9+/=]', '', data or "")               # Strip illegal chars for base64
        pad_len = len(cleaned) % 4                                         # Compute padding requirement
        if pad_len:                                                        # Pad to multiple of 4 if needed
            cleaned += '=' * (4 - pad_len)
        return cleaned                                                     # Return normalized base64
    except Exception as e:
        logging.error(f"Base64 cleaning failed: {e}")                      # Log error; return original
        return data or ""

def try_decompress(data: bytes) -> bytes:
    # Attempt known compression schemes in order; return first that works
    methods = [
        ("gzip", lambda: gzip.decompress(data)),                           # Try gzip container
        ("zlib (raw)", lambda: decompress(data, -15)),                     # Try raw deflate
        ("zlib (with header)", lambda: decompress(data)),                  # Try zlib w/ header
        ("no compression", lambda: data),                                  # Fallback: assume uncompressed
    ]
    for name, method in methods:
        try:
            out = method()                                                 # Attempt method
            logging.info(f"Success with {name} decompression")             # Log which one worked
            return out                                                     # Return decompressed bytes
        except Exception as e:
            logging.debug(f"Decompression failed with {name}: {str(e)[:120]}")  # Debug failure and continue
    return data                                                             # If all fail, return original bytes

# =============================================================================
# Shape helpers
# =============================================================================
def _is_columnar_dict(obj) -> bool:
    if not isinstance(obj, dict) or not obj:                               # Must be a non-empty dict
        return False
    lengths = set()                                                        # Track list lengths per column
    for v in obj.values():
        if not isinstance(v, list):                                        # All values must be lists
            return False
        lengths.add(len(v))                                                # Record list length
        if len(lengths) > 1 and 0 not in lengths:                          # Mixed nonzero lengths → invalid
            return False
    return True                                                            # Valid columnar dict (equal lengths)

def _normalize_columnar(col_dict: dict) -> dict:
    out = {}
    for k, vals in col_dict.items():                                       # For each column
        norm = []
        for v in vals:                                                     # Normalize each cell to string/None
            if isinstance(v, (dict, list)):
                norm.append(json.dumps(v, ensure_ascii=False))             # JSON encode complex types
            elif hasattr(v, "isoformat"):
                norm.append(v.isoformat())                                 # Datetime-like to ISO string
            elif v is None:
                norm.append(None)                                          # Preserve nulls
            else:
                norm.append(str(v))                                        # Force to string
        out[k] = norm                                                      # Save normalized column
    return out

def _merge_columnars(dicts: list[dict]) -> dict:
    if not dicts:
        return {}                                                          # Nothing to merge
    keys = set()
    for d in dicts:
        keys.update(d.keys())                                              # Union of all columns
    lengths = [next((len(v) for v in d.values()), 0) for d in dicts]       # Row counts per fragment
    merged = {k: [] for k in keys}                                         # Prepare merged columns
    for d, dl in zip(dicts, lengths):                                      # For each fragment and its length
        for k in keys:
            if k in d:
                merged[k].extend(d[k])                                     # Append actual values
            else:
                merged[k].extend([None] * dl)                              # Pad missing columns with nulls
    return merged

def _flatten_decoded_rows(decoded):
    if isinstance(decoded, list):
        return [r for r in decoded if isinstance(r, dict)]                 # Keep only dict rows
    if isinstance(decoded, dict):
        return [decoded]                                                   # Single dict becomes one row
    return []                                                              # Otherwise no rows

def _rows_to_columnar(rows: list[dict]) -> dict:
    if not rows:
        return {}                                                          # No rows → empty
    seen = []                                                              # Maintain first-seen column order
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.append(k)                                             # Record new column name
    out = {k: [] for k in seen}                                            # Initialize columns
    for r in rows:
        for k in seen:                                                     # Preserve column order across rows
            v = r.get(k, None)                                             # Missing keys → None
            if isinstance(v, (dict, list)):
                out[k].append(json.dumps(v, ensure_ascii=False))           # JSON encode complex values
            elif hasattr(v, "isoformat"):
                out[k].append(v.isoformat())                               # Datetime-like to ISO string
            elif v is None:
                out[k].append(None)                                        # Pass through None
            else:
                out[k].append(str(v))                                      # Force to string
    return out

# =============================================================================
# Writers
# =============================================================================
def _upload_bytes(blob_service_client: BlobServiceClient, blob_path: str, data: bytes) -> str:
    blob_client = blob_service_client.get_blob_client(                     # Get a blob client for path
        container=_req("OUTPUT_CONTAINER"),
        blob=blob_path
    )
    blob_client.upload_blob(data, overwrite=True)                          # Upload bytes; overwrite enabled
    logging.info(f"Wrote: {_req('OUTPUT_CONTAINER')}/{blob_path}")         # Log the final blob path
    return blob_client.url                                                 # Return blob URL (useful for tracing)

def _columnar_to_single_row_table(columnar_dict: dict) -> pa.Table:
    arrays, fields = [], []                                                # Accumulate Arrow arrays & fields
    for col_name, values in columnar_dict.items():
        str_values = [str(v) if v is not None else None for v in values]   # Ensure values are strings/None
        fields.append(pa.field(col_name, pa.list_(pa.string())))           # Column type: LIST<STRING>
        arrays.append(pa.array([str_values], type=pa.list_(pa.string())))  # Single row with list cell
    schema = pa.schema(fields)                                             # Build schema from fields
    return pa.Table.from_arrays(arrays, schema=schema)                     # Create Arrow table

def _write_parquet_under_folder(
    bsc: BlobServiceClient,
    folder: str,
    filename: str,
    columnar_dict: dict,
    meta: dict | None = None
) -> str:
    arrow_table = _columnar_to_single_row_table(columnar_dict)             # Convert dict → Arrow table
    if meta:
        arrow_table = arrow_table.replace_schema_metadata(                 # Attach small metadata to schema
            {k: str(v) for k, v in meta.items()}
        )
    buf = io.BytesIO()                                                     # In-memory bytes buffer
    pq.write_table(arrow_table, buf, compression=PARQUET_COMPRESSION)      # Write Parquet to buffer
    buf.seek(0)                                                            # Rewind to start for upload
    try:
        base_path = _join_path(OUTPUT_PREFIX or "", folder)                # Combine optional prefix + folder
        return _upload_bytes(bsc, f"{base_path}/{filename}", buf.read())   # Upload and return URL
    finally:
        buf.close()                                                        # Always release buffer

# =============================================================================
# Message processing
# =============================================================================
def process_single_message(message: dict) -> dict:
    result = {
        "Original": message,                                               # Preserve original message
        "DecodedData": None,                                               # Placeholder for decoded JSON
        "DecodedShape": None,                                              # "rows" or "columnar"
    }
    if "Data" not in message:                                              # If no payload, return as-is
        return result

    try:
        cleaned = clean_base64(str(message["Data"]))                       # Normalize base64 string
        decoded_bytes = base64.b64decode(cleaned)                          # Decode base64 → bytes
        decompressed = try_decompress(decoded_bytes)                       # Try to decompress if needed

        try:
            decoded_json = json.loads(decompressed.decode("utf-8"))        # Parse bytes → JSON
            result["DecodedData"] = decoded_json                           # Store decoded JSON
            if isinstance(decoded_json, dict) and _is_columnar_dict(decoded_json):
                result["DecodedShape"] = "columnar"                        # Dict of equal-length lists
            elif isinstance(decoded_json, list):
                result["DecodedShape"] = "rows"                            # List of row dicts
            else:
                result["DecodedShape"] = "rows"                            # Single dict → one row
        except Exception:
            result["DecodedData"] = None                                   # Not JSON → ignore payload
            result["DecodedShape"] = None

    except Exception as e:
        logging.error(f"Data processing failed: {e}")                      # Log failure (base64/decompress)

    return result                                                          # Return processing outcome

# =============================================================================
# Event Hub Trigger (all values come from app settings via binding expressions)
# =============================================================================
@app.function_name("EventHubIngest")                                       # Name of the Function
@app.event_hub_message_trigger(
    arg_name="azeventhub",                                                 # Parameter name in function
    event_hub_name="%EVENTHUB_NAME%",                                      # EH name from app setting
    connection="EVENTHUB_MANAGEDIDENTITY_CONNECTION", # <-- prefix (no % %)
    consumer_group="%EVENTHUB_CONSUMER_GROUP%"                             # Consumer group from app setting
    # add cardinality="many" if you want batch input                         # (not used here)
)
def eventhub_trigger(azeventhub: func.EventHubEvent):
    """
    Main Event Hub trigger.
    Writes ONLY the decoded Parquet artifact per (folder, table) group.
    """
    try:
        bsc = initialize_blob_client()                                     # Build Blob client from env
        ensure_target_container(bsc)                                       # Ensure container exists

        message_body = azeventhub.get_body().decode("utf-8")               # Read raw body from EH event
        logging.info(f"Received message batch (size: {len(message_body)} bytes)")  # Log size for trace

        try:
            message_data = json.loads(message_body)                         # Try JSON parse (array or object)
        except json.JSONDecodeError:
            message_data = {"Data": message_body}                           # Fallback: treat raw as Data string

        messages = message_data if isinstance(message_data, list) else [message_data]  # Normalize to list

        processed = []
        for msg in messages:
            try:
                processed.append(process_single_message(msg))               # Decode/decompress each message
            except Exception as e:
                logging.error(f"Failed to process message: {e}")            # Log and continue next

        grouped: dict[tuple[str, str, str], list[dict]] = {}                # Key: (folder, source_db, table)
        for item in processed:
            folder, source_db, table = resolve_folder_and_table(item.get("Original", {}))  # Routing
            if not folder or not table:                                     # Skip if routing invalid
                logging.warning(f"Skipping due to invalid routing: {item.get('Original')}")
                continue
            grouped.setdefault((folder, source_db, table), []).append(item) # Group items by route

        for (folder, source_db, table), group_items in grouped.items():     # Handle each group independently
            try:
                ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")             # Timestamp for file naming

                decoded_rows_all = []                                       # Accumulate row-wise payloads
                columnar_payloads = []                                      # Accumulate columnar payloads

                for it in group_items:
                    dd = it.get("DecodedData")                              # Decoded JSON (dict/list/None)
                    shape = it.get("DecodedShape")                          # "rows", "columnar", or None
                    if dd is None or shape is None:                         # Skip if no usable payload
                        continue
                    if shape == "columnar" and isinstance(dd, dict):
                        columnar_payloads.append(_normalize_columnar(dd))   # Normalize and store columnar
                    else:
                        decoded_rows_all.extend(_flatten_decoded_rows(dd))  # Flatten rows and append

                col_from_rows = _rows_to_columnar(decoded_rows_all) if decoded_rows_all else {}  # Rows→columns
                col_merged_payloads = (                                     # Merge multiple columnar fragments
                    _merge_columnars(columnar_payloads) if len(columnar_payloads) > 1
                    else (columnar_payloads[0] if columnar_payloads else {})
                )

                final_parts = []                                            # Pieces to combine
                if col_from_rows:
                    final_parts.append(col_from_rows)                       # Add rows-converted columns
                if col_merged_payloads:
                    final_parts.append(col_merged_payloads)                 # Add columnar merges

                if not final_parts:                                         # If nothing to write → skip
                    logging.info(f"No decoded JSON data for {folder}/{table}; decoded parquet skipped.")
                    continue

                final_columnar = _merge_columnars(final_parts) if len(final_parts) > 1 else final_parts[0]  # Final table

                rows_count = next((len(v) for v in final_columnar.values()), 0)  # Infer row count from any column
                base_name = f"{table}_{ts}"                                 # Base filename (table + timestamp)

                if rows_count > MAX_BATCH_SIZE:                             # Chunk very large payloads
                    start = 0
                    batch_index = 0
                    while start < rows_count:
                        end = min(start + MAX_BATCH_SIZE, rows_count)       # Compute window end
                        sliced = {k: v[start:end] for k, v in final_columnar.items()}  # Slice each column
                        parquet_name = f"{base_name}_part{batch_index:04d}.parquet"   # Chunked file name
                        _write_parquet_under_folder(                        # Write chunk to blob
                            bsc, folder, parquet_name, sliced,
                            meta={
                                "kind": "decoded_payload",                  # Small metadata in schema
                                "row_count": end - start,
                                "batch_number": batch_index,
                                "folder": folder,
                                "source_db": source_db,
                                "table": table,
                            },
                        )
                        batch_index += 1                                    # Next chunk index
                        start = end                                         # Advance window
                else:
                    parquet_name = f"{base_name}.parquet"                   # Single-file case
                    _write_parquet_under_folder(                            # Write entire payload
                        bsc, folder, parquet_name, final_columnar,
                        meta={
                            "kind": "decoded_payload",
                            "row_count": rows_count,
                            "batch_number": 0,
                            "folder": folder,
                            "source_db": source_db,
                            "table": table,
                        },
                    )

            except Exception as e:
                logging.error(f"Failed to write group {folder}/{table}: {e}")   # Log group-level failure

        logging.info("Processing complete (emitted decoded parquet per group only).")  # End-of-run info

    except Exception as e:
        logging.error(f"Critical processing failure: {e}")                  # Catch-all for trigger scope
        raise                                                               # Re-raise so platform can handle
