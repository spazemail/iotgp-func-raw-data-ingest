###############################
# 1. Application Insights
###############################

# Create application insights
resource "azurerm_application_insights" "application_insights" {
  count               = var.app_insights_enabled == "True" ? 1 : 0
  name                = "${var.app_acronym}-${var.environment}-appinsights-${var.function_name}-${var.seq_number}-${var.location_acronym}"
  location            = var.location
  resource_group_name = var.resource_group
  application_type    = "web"
  workspace_id        = data.azurerm_log_analytics_workspace.log_analytics.id

  tags = {
    Provider  = "Innowave"
    Rateio    = "clientes"
    SLA       = "IT"
    StartDate = "07/08/2025"
  }
}

###############################
# 2. Upload Function ZIP to Blob
###############################
#have to discuss
# Put zip file with function source code in storage account as blob
resource "azurerm_storage_blob" "storage_blob_function" {
  name                   = "${var.function_name}-function-${substr(data.local_file.function_files.content_md5, 0, 6)}.zip"
  storage_account_name   = data.azurerm_storage_account.function_storage.name
  storage_container_name = azurerm_storage_container.function_releases_container.name
  type                   = "Block"
  content_md5            = data.local_file.function_files.content_md5
  source                 = var.artifact_zip
}

# ==========================
#  Linux App Service Plan
# ==========================
resource "azurerm_service_plan" "function_service_plan" {
  name                = "${var.app_acronym}-${var.environment}-plan-${var.function_name}-${var.seq_number}-${var.location_acronym}"
  location            = var.location
  resource_group_name = var.resource_group
 
  os_type  = "Linux"          # <<< IMPORTANT: Linux (fixes the Windows plan mismatch)
  sku_name = "Y1"             # Consumption plan (alternatives: EP1 for Premium, B1/P1v3 for Dedicated)
 
  # For EP plans you may add:
  # worker_count     = 1
  # per_site_scaling = false
}
 
 
###############################
# 3. Linux Function App (Python)
###############################
resource "azurerm_linux_function_app" "eventhub_function_app" {
  name                       = "${var.app_acronym}-${var.environment}-func-${var.function_name}-${var.seq_number}-${var.location_acronym}-01"
  location                   = var.location
  resource_group_name        = var.resource_group
 
  # CHANGED: was data.azurerm_service_plan.function_service_plan.id
  service_plan_id            = azurerm_service_plan.function_service_plan.id
 
  storage_account_name       = data.azurerm_storage_account.function_storage.name
  storage_account_access_key = data.azurerm_storage_account.function_storage.primary_access_key
 
  # Keep Zip Deploy (no WEBSITE_RUN_FROM_PACKAGE)
  zip_deploy_file = var.artifact_zip
 
  site_config {
    application_stack { python_version = "3.10" }
  }
 
  identity { type = "SystemAssigned" }
 
  app_settings = {
  FUNCTIONS_WORKER_RUNTIME = "python"
  FUNCTIONS_EXTENSION_VERSION = "~4"

  # your existing ones...
  OUTPUT_CONTAINER     = "databases"
  MAX_BATCH_SIZE       = "2000"
  PARQUET_COMPRESSION  = "SNAPPY"
  DESTINATION_FALLBACK = "assorted"
  WRITE_DECODED_ONLY   = "true"
  LOG_LEVEL            = "INFO"
  AzureWebJobsStorage  = data.azurerm_storage_account.function_storage.primary_connection_string

  # for convenience if you still reference them in code
  EVENTHUB_NAME           = azurerm_eventhub.eventhub_driver_messages.name
  EVENTHUB_CONSUMER_GROUP = azurerm_eventhub_consumer_group.eventhub_driver_message_consumer_group.name

  # **Managed Identity connection prefix**
  EVENTHUB_MANAGEDIDENTITY_CONNECTION__fullyQualifiedNamespace = "${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  EVENTHUB_MANAGEDIDENTITY_CONNECTION__eventHubName            = azurerm_eventhub.eventhub_driver_messages.name
  EVENTHUB_MANAGEDIDENTITY_CONNECTION__credential              = "managedidentity"
  # If using UAMI instead of system-assigned:
  # EVENTHUB_MANAGEDIDENTITY_CONNECTION__clientId = azurerm_user_assigned_identity.func_uami.client_id
}

 
  tags = {
    Provider  = "Innowave"
    Rateio    = "clientes"
    SLA       = "IT"
    StartDate = "05/08/2025"
  }
 
  # Optional but helpful: ensure plan exists first
  depends_on = [azurerm_service_plan.function_service_plan]
}

###############################
# 4. Role Assignments
###############################
# Allow Function App to read from Event Hub
resource "azurerm_role_assignment" "eventhub_role_assignment" {
  principal_id         = azurerm_linux_function_app.eventhub_function_app.identity[0].principal_id
  role_definition_name = "Azure Event Hubs Data Receiver"
  scope                = azurerm_eventhub.eventhub_driver_messages.id
}

# Allow Function App to write to Storage (Blob)
resource "azurerm_role_assignment" "storage_blob_contributor" {
  principal_id         = azurerm_linux_function_app.eventhub_function_app.identity[0].principal_id
  role_definition_name = "Storage Blob Data Contributor"
  scope                = data.azurerm_storage_account.function_storage.id
}
