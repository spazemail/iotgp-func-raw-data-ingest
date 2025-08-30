# IoT Hub -> Event Hub endpoint (keyBased)
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "EventHubMessages2"

  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name

  authentication_type = "keyBased"
  connection_string   = azurerm_eventhub_namespace_authorization_rule.ehns_send.primary_connection_string
}

resource "azurerm_iothub_route" "telemetry_to_custom_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "TelemetryToEventHub"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'TelemetryData'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name]
  enabled        = true

  lifecycle {
    replace_triggered_by = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.id]
  }
}
