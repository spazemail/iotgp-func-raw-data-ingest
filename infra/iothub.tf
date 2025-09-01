
# -----------------------------
# Role assignment (IoT Hub MI -> EH sender)
# Scope can be the specific Event Hub *or* the namespace.
# Prefer the *Event Hub* scope least-privilege:
# -----------------------------
resource "azurerm_role_assignment" "iothub_eventhub_sender" {
  scope                = azurerm_eventhub.eventhub_driver_messages.id   # or data.azurerm_eventhub_namespace.eventhubs_namespace.id
  role_definition_name = "Azure Event Hubs Data Sender"

  # Use the IoT Hub's system-assigned identity
  principal_id         = data.azurerm_iothub.iothub.identity[0].principal_id
}

# -----------------------------
# IoT Hub -> Event Hub endpoint (identity-based)
# NOTE: No connection_string. MSI is used.
# -----------------------------
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "SqlIngestionToEvents2"

  # NAMESPACE in URI; Event Hub in entity_path
  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name

  authentication_type = "identityBased"


}

# -----------------------------
# Route DeviceMessages -> custom EH endpoint
# -----------------------------
resource "azurerm_iothub_route" "telemetry_to_custom_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToEvents2"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name]
  enabled        = true

  lifecycle {
    replace_triggered_by = [
      azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.id
    ]
  }
}
