# Role assignment: IoT Hub MSI can send to Event Hub namespace
resource "azurerm_role_assignment" "iothub_role_eventhub_sender" {
  scope                = data.azurerm_eventhub_namespace.eventhubs_namespace.id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = azurerm_iothub.my_iothub.identity[0].principal_id
}



# --- 1) IoT Hub → Event Hub custom endpoint (Managed Identity) ---
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "EventHubMessages2"  # keep this exact; used by the route below

  # NOTE: uri uses the NAMESPACE name; path uses the EH (entity) name
  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name

  authentication_type = "identityBased"
}

# --- 2a) Route DeviceMessages (TelemetryData) to the CUSTOM endpoint ---
resource "azurerm_iothub_route" "telemetry_to_custom_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "TelemetryToEventHub"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'TelemetryData'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name]  # == "EventHubMessages2"
  enabled        = true

  lifecycle {
    replace_triggered_by = [
      azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.id
    ]
  }
}
