
## Create route for Telemetry Data for previous endpoint 
resource "azurerm_iothub_route" "iothub_route_eventhub_messages_endpoint" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToEventHub2"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = \"Raw\""
  endpoint_names = [ azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name ]
  enabled        = true
}