data "local_file" "function_files" {
  filename  = "${var.artifact_zip}"
}
# Reference existing Storage Account
data "azurerm_storage_account" "function_storage" {
  name                = var.storage_account_name
  resource_group_name = var.resource_group
}

# Reference existing Event Hub Namespace
data "azurerm_eventhub_namespace" "eventhubs_namespace" {
  name                = var.eventhubs_namespace
  resource_group_name = var.resource_group
}

# Reference existing Log Analytics Workspace
data "azurerm_log_analytics_workspace" "log_analytics" {
  name                = var.log_analytics_name
  resource_group_name = var.resource_group
}

# Reference to existing IotHub
data "azurerm_iothub" "iothub" {
  name                = var.iothub_name
  resource_group_name = var.resource_group
}

