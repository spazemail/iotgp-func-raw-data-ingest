# Route DeviceMessages ('Raw') to the EXISTING custom EH endpoint

resource "azurerm_iothub_route" "sql_ingestion_to_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToEventHub2"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"
  endpoint_names = ["SqlIngestionToEventHub"]  # exact name from the portal
  enabled        = true
}
