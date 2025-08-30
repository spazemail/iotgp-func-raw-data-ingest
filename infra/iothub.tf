
# 1) IoT Hub → Event Hub custom endpoint
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "EventHubMessages"

  endpoint_uri        = "sb://${azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_messages.name
  authentication_type = "identityBased"
}

# 2) Route DeviceMessages (TelemetryData) to that custom endpoint
resource "azurerm_iothub_route" "telemetry_to_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "TelemetryToEventHub"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'TelemetryData'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name]
  enabled        = true
}
