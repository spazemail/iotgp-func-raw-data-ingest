# Route DeviceMessages ('Raw') to the EXISTING custom EH endpoint
resource "azurerm_iothub_route" "sql_ingestion_to_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToEventHub2"   # route name (any unique name)

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"      # or: LOWER($body.MessageType) = 'raw'
  endpoint_names = ["SqlIngestionToEventHub"]       # <-- exact endpoint name from portal
  enabled        = true
}
