import azure.functions as func
import logging
import base64
import gzip
import io
import re
import json
import os
from datetime import datetime
from zlib import decompress
import pyarrow as pa
import pyarrow.parquet as pq
from azure.storage.blob import BlobServiceClient

# Single FunctionApp instance
app = func.FunctionApp()

# =============================================================================
# Configuration
# =============================================================================
# Connection string for Blob Storage (must be set in Function App settings)
BLOB_CONNECTION_STRING = os.getenv("AzureWebJobsStorage")

# Protects very large payloads by chunking the decoded rows into batches when writing Parquet
MAX_BATCH_SIZE = 2000

# All outputs go into this single container; "folders" are virtual via blob path naming
TARGET_CONTAINER = os.getenv("OUTPUT_CONTAINER", "databases")

# Allowed characters for safe parsing from Source field (db.table)
_NAME_KEEP = re.compile(r'[^a-zA-Z0-9._-]')


# =============================================================================
# Storage helpers
# =============================================================================
def initialize_blob_client() -> BlobServiceClient:
    """
    Initialize BlobServiceClient using the configured connection string.
    Raises on failure so the function ends clearly if storage is unreachable.
    """
    # FIX: fail fast if missing connection string
    if not BLOB_CONNECTION_STRING:
        raise RuntimeError("AzureWebJobsStorage is not configured")
    try:
        return BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
    except Exception as e:
        logging.error(f"Blob storage initialization failed: {e}")
        raise


def ensure_target_container(blob_service_client: BlobServiceClient):
    """
    Ensure the target container exists (create if not).
    NOTE: Azure Blob "folders" are virtual; we do NOT create folders explicitly.
    """
    try:
        container_client = blob_service_client.get_container_client(TARGET_CONTAINER)
        if not container_client.exists():
            container_client.create_container()
            logging.info(f"Created container: {TARGET_CONTAINER}")
        return container_client
    except Exception as e:
        logging.error(f"Failed to ensure container {TARGET_CONTAINER}: {e}")
        raise


# =============================================================================
# Name sanitization
# =============================================================================
def _sanitize_folder(name: str) -> str:
    """
    Sanitize a folder (top-level path segment) name:
      - lowercase
      - keep only [a-z0-9_-]
      - replace everything else with underscore
    """
    return re.sub(r'[^a-z0-9_-]+', '_', (name or '').strip().lower())


def _sanitize_table(name: str) -> str:
    """
    Sanitize a table/file-stem name with the same rules as folder.
    """
    return re.sub(r'[^a-z0-9_-]+', '_', (name or '').strip().lower())


# =============================================================================
# Folder / table resolution
# =============================================================================
def resolve_folder_and_table(message: dict) -> tuple[str, str, str]:
    """
    Decide the output routing and naming from an input message.

    Folder (first virtual folder under the container):
      1) If 'Destination' is present and non-empty → use Destination
      2) Else → use literal folder name 'assorted' (NO fallback to DB)

    Table:
      - Parse from 'Source' as the substring after the first dot
      - If 'Source' has no dot, use the whole 'Source'
      - If absent/empty, use 'unknown_table'

    Also parse source_db (for metadata only):
      - DB part of 'Source' (substring before the first dot)
      - If no dot, it equals the whole 'Source'
      - If absent/empty, use 'unknown_db'
    """
    # Clean raw 'Source' so we only keep safe characters
    source = str(message.get("Source", "")).strip()
    source = _NAME_KEEP.sub("", source)

    # Split Source into db and table parts (db.table); if no dot, both become Source
    if '.' in source:
        db_part, table_part = source.split('.', 1)
    else:
        db_part, table_part = source, source

    # Folder selection rule: Destination > 'assorted'
    raw_destination = str(message.get("Destination") or "").strip()
    folder_source = raw_destination if raw_destination else "assorted"

    # Final sanitized parts
    folder     = _sanitize_folder(folder_source or "assorted")
    source_db  = _sanitize_folder(db_part or "unknown_db")
    table_name = _sanitize_table(table_part or "unknown_table")

    return folder, source_db, table_name


# =============================================================================
# Decode / Decompress helpers
# =============================================================================
def clean_base64(data: str) -> str:
    """
    Remove invalid characters and pad base64 string to a multiple of 4.
    Safe for both padded and unpadded inputs.
    """
    try:
        cleaned = re.sub(r'[^A-Za-z0-9+/=]', '', data or "")
        pad_len = len(cleaned) % 4
        if pad_len:
            cleaned += '=' * (4 - pad_len)
        return cleaned
    except Exception as e:
        logging.error(f"Base64 cleaning failed: {e}")
        return data or ""


def try_decompress(data: bytes) -> bytes:
    """
    Attempt gzip, then zlib (raw), then zlib (with header); if all fail, return original bytes.
    This allows flexible handling of various producer compression schemes.
    """
    methods = [
        ("gzip", lambda: gzip.decompress(data)),
        ("zlib (raw)", lambda: decompress(data, -15)),
        ("zlib (with header)", lambda: decompress(data)),
        ("no compression", lambda: data),
    ]
    for name, method in methods:
        try:
            out = method()
            logging.info(f"Success with {name} decompression")
            return out
        except Exception as e:
            logging.warning(f"Decompression failed with {name}: {str(e)[:120]}")
    return data


# =============================================================================
# Shape helpers (row-wise ↔ columnar)
# =============================================================================
def _is_columnar_dict(obj) -> bool:
    """
    True if obj is a dict where each value is a list and all lists have equal length (or all empty).
      Example: {"colA": ["a","b"], "colB": ["1","2"]}
    """
    if not isinstance(obj, dict) or not obj:
        return False
    lengths = set()
    for v in obj.values():
        if not isinstance(v, list):
            return False
        lengths.add(len(v))
        if len(lengths) > 1 and 0 not in lengths:
            return False
    return True


def _normalize_columnar(col_dict: dict) -> dict:
    """
    Normalize a columnar dict so every list element is a string or None.
    - dict/list values are JSON-encoded strings
    - datetime-like values use isoformat()
    """
    out = {}
    for k, vals in col_dict.items():
        norm = []
        for v in vals:
            if isinstance(v, (dict, list)):
                norm.append(json.dumps(v, ensure_ascii=False))
            elif hasattr(v, "isoformat"):
                norm.append(v.isoformat())
            elif v is None:
                norm.append(None)
            else:
                norm.append(str(v))
        out[k] = norm
    return out


def _merge_columnars(dicts: list[dict]) -> dict:
    """
    Concatenate multiple columnar dicts into one.
    Keys are the union; missing keys are padded with None.
    """
    if not dicts:
        return {}
    keys = set()
    for d in dicts:
        keys.update(d.keys())
    lengths = [next((len(v) for v in d.values()), 0) for d in dicts]
    merged = {k: [] for k in keys}
    for d, dl in zip(dicts, lengths):
        for k in keys:
            if k in d:
                merged[k].extend(d[k])
            else:
                merged[k].extend([None] * dl)
    return merged


def _flatten_decoded_rows(decoded):
    """
    Convert decoded payload into list of row dicts (row-wise JSON).
    - list[dict] → list[dict]
    - dict → [dict]
    - otherwise → []
    """
    if isinstance(decoded, list):
        return [r for r in decoded if isinstance(r, dict)]
    if isinstance(decoded, dict):
        return [decoded]
    return []


def _rows_to_columnar(rows: list[dict]) -> dict:
    """
    Convert a list of row dicts into a columnar dict: {col: [values...]}.
    Preserves first-seen key order across rows.
    """
    if not rows:
        return {}
    seen = []
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.append(k)
    out = {k: [] for k in seen}
    for r in rows:
        for k in seen:
            v = r.get(k, None)
            if isinstance(v, (dict, list)):
                out[k].append(json.dumps(v, ensure_ascii=False))
            elif hasattr(v, "isoformat"):
                out[k].append(v.isoformat())
            elif v is None:
                out[k].append(None)
            else:
                out[k].append(str(v))
    return out


# =============================================================================
# Writers
# =============================================================================
def _upload_bytes(blob_service_client: BlobServiceClient, blob_path: str, data: bytes) -> str:
    """
    Upload raw bytes to '<container>/<blob_path>'.
    'blob_path' may include virtual folders, e.g. 'folder/filename.ext'
    """
    blob_client = blob_service_client.get_blob_client(container=TARGET_CONTAINER, blob=blob_path)
    blob_client.upload_blob(data, overwrite=True)
    logging.info(f"Wrote: {TARGET_CONTAINER}/{blob_path}")
    return blob_client.url


def _columnar_to_single_row_table(columnar_dict: dict) -> pa.Table:
    """
    Create a single-row Arrow table where each column is LIST<STRING>.
    This keeps potentially huge lists compact in one row.
    """
    arrays, fields = [], []
    for col_name, values in columnar_dict.items():
        str_values = [str(v) if v is not None else None for v in values]
        fields.append(pa.field(col_name, pa.list_(pa.string())))
        arrays.append(pa.array([str_values], type=pa.list_(pa.string())))
    schema = pa.schema(fields)
    return pa.Table.from_arrays(arrays, schema=schema)


def _write_parquet_under_folder(
    bsc: BlobServiceClient,
    folder: str,
    filename: str,
    columnar_dict: dict,
    meta: dict | None = None
) -> str:
    """
    Serialize a columnar dict to Parquet and upload under 'folder/filename'.
    Adds optional schema metadata (e.g., row_count, table, etc.).
    """
    arrow_table = _columnar_to_single_row_table(columnar_dict)
    if meta:
        arrow_table = arrow_table.replace_schema_metadata({k: str(v) for k, v in meta.items()})
    buf = io.BytesIO()
    pq.write_table(arrow_table, buf, compression="SNAPPY")
    buf.seek(0)
    try:
        return _upload_bytes(bsc, f"{folder}/{filename}", buf.read())
    finally:
        buf.close()


# =============================================================================
# Message processing
# =============================================================================
def process_single_message(message: dict) -> dict:
    """
    Decode + decompress one message's 'Data' (if present) and detect its shape.

    Returns a record containing:
      - Original (full original message)
      - DecodedData (dict | list | None)
      - DecodedShape ("columnar" | "rows" | None)
    """
    result = {
        "Original": message,
        "DecodedData": None,
        "DecodedShape": None,
    }
    if "Data" not in message:
        return result

    try:
        cleaned = clean_base64(str(message["Data"]))
        decoded_bytes = base64.b64decode(cleaned)
        decompressed = try_decompress(decoded_bytes)

        try:
            decoded_json = json.loads(decompressed.decode("utf-8"))
            result["DecodedData"] = decoded_json
            if isinstance(decoded_json, dict) and _is_columnar_dict(decoded_json):
                result["DecodedShape"] = "columnar"
            elif isinstance(decoded_json, list):
                result["DecodedShape"] = "rows"
            else:
                # Single dict treated as one row
                result["DecodedShape"] = "rows"
        except Exception:
            # Not JSON → ignore (we only persist JSON payloads)
            result["DecodedData"] = None
            result["DecodedShape"] = None

    except Exception as e:
        logging.error(f"Data processing failed: {e}")

    return result


# =============================================================================
# Event Hub Trigger
# =============================================================================
@app.function_name("EventHubIngest")
@app.event_hub_message_trigger(
    arg_name="azeventhub",
    event_hub_name="iotgp-prd-eventhub-smartqos-01-we",  # ensure this matches your EH name
    connection="EVENTHUB_MANAGEDIDENTITY_CONNECTION",      # app setting name
    consumer_group="function-consumer"                     # FIX: added missing comma above
    # NOTE: if you want batch input, add: cardinality="many"
)
def eventhub_trigger(azeventhub: func.EventHubEvent):
    """
    Main Event Hub trigger.

    For each (folder, table) group, writes ONLY the decoded Parquet artifact:
      - <TABLENAME>_<YYYYMMDDHHMMSS>[_partNNNN].parquet

    Folder selection summary:
      - Use message['Destination'] if provided and non-empty
      - Otherwise write to literal folder 'assorted'
    """
    try:
        bsc = initialize_blob_client()
        ensure_target_container(bsc)

        # Read the Event Hub batch body
        message_body = azeventhub.get_body().decode("utf-8")
        logging.info(f"Received message batch (size: {len(message_body)} bytes)")

        # Accept either JSON array/object or raw text (wrap raw text into {"Data": ...})
        try:
            message_data = json.loads(message_body)
        except json.JSONDecodeError:
            message_data = {"Data": message_body}

        messages = message_data if isinstance(message_data, list) else [message_data]

        # Decode/decompress each message; shape detection happens inside
        processed = []
        for msg in messages:
            try:
                processed.append(process_single_message(msg))
            except Exception as e:
                logging.error(f"Failed to process message: {e}")

        # Group by (folder, source_db, table) derived from the ORIGINAL message
        grouped: dict[tuple[str, str, str], list[dict]] = {}
        for item in processed:
            folder, source_db, table = resolve_folder_and_table(item.get("Original", {}))
            if not folder or not table:
                logging.warning(f"Skipping due to invalid routing: {item.get('Original')}")
                continue
            grouped.setdefault((folder, source_db, table), []).append(item)

        # Per group → write ONLY the decoded Parquet
        for (folder, source_db, table), group_items in grouped.items():
            try:
                ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")

                # Gather decoded payloads across messages
                decoded_rows_all = []
                columnar_payloads = []

                for it in group_items:
                    dd = it.get("DecodedData")
                    shape = it.get("DecodedShape")
                    if dd is None or shape is None:
                        continue
                    if shape == "columnar" and isinstance(dd, dict):
                        columnar_payloads.append(_normalize_columnar(dd))
                    else:
                        decoded_rows_all.extend(_flatten_decoded_rows(dd))

                # Build final columnar dict for decoded Parquet
                col_from_rows = _rows_to_columnar(decoded_rows_all) if decoded_rows_all else {}
                col_merged_payloads = (
                    _merge_columnars(columnar_payloads) if len(columnar_payloads) > 1
                    else (columnar_payloads[0] if columnar_payloads else {})
                )

                final_parts = []
                if col_from_rows:
                    final_parts.append(col_from_rows)
                if col_merged_payloads:
                    final_parts.append(col_merged_payloads)

                if not final_parts:
                    logging.info(f"No decoded JSON data for {folder}/{table}; decoded parquet skipped.")
                    continue

                final_columnar = _merge_columnars(final_parts) if len(final_parts) > 1 else final_parts[0]

                # Chunk Parquet by MAX_BATCH_SIZE to protect against huge list-cells
                rows_count = next((len(v) for v in final_columnar.values()), 0)
                if rows_count > MAX_BATCH_SIZE:
                    start = 0
                    batch_index = 0
                    while start < rows_count:
                        end = min(start + MAX_BATCH_SIZE, rows_count)
                        sliced = {k: v[start:end] for k, v in final_columnar.items()}

                        # FIX: unique name per chunk to avoid overwrite
                        parquet_name = f"{table}_{ts}_part{batch_index:04d}.parquet"
                        _write_parquet_under_folder(
                            bsc, folder, parquet_name, sliced,
                            meta={
                                "kind": "decoded_payload",
                                "row_count": end - start,
                                "batch_number": batch_index,
                                "folder": folder,
                                "source_db": source_db,
                                "table": table,
                            },
                        )
                        batch_index += 1
                        start = end
                else:
                    parquet_name = f"{table}_{ts}.parquet"
                    _write_parquet_under_folder(
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
                logging.error(f"Failed to write group {folder}/{table}: {e}")

        logging.info("Processing complete (emitted decoded parquet per group only).")

    except Exception as e:
        logging.error(f"Critical processing failure: {e}")
        raise
