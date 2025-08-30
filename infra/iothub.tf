# -----------------------------
# IoT Hub -> Event Hub endpoint (keyBased)
# -----------------------------
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "EventHubMessages2"

  # NAMESPACE in URI, Event Hub name as entity path
  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name

  authentication_type = "keyBased"
  connection_string   = azurerm_eventhub_namespace_authorization_rule.ehns_send.primary_connection_string
}

# -----------------------------
# Route DeviceMessages -> custom EH endpoint
# -----------------------------
resource "azurerm_iothub_route" "telemetry_to_custom_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "TelemetryToEventHub"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'TelemetryData'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name]
  enabled        = true

  # Recreate route if endpoint id changes (safe)
  lifecycle {
    replace_triggered_by = [
      azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.id
    ]
  }
}
