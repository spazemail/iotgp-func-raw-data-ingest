# Create a custom Event Hub endpoint on the IoT Hub
resource "azurerm_iothub_endpoint_eventhub" "eh_ep" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "SqlIngestionToEventHub"   # <-- your custom name
  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name
  authentication_type = "identityBased"
}

# Route to that custom endpoint
resource "azurerm_iothub_route" "to_custom" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToEH"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.eh_ep.name]  # "SqlIngestionToEventHub"
  enabled        = true
}
