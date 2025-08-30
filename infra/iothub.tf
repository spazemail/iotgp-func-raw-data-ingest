
# -----------------------------
# Role assignment (IoT Hub MI -> EH sender)
# Scope can be the specific Event Hub *or* the namespace.
# Prefer the *Event Hub* scope least-privilege:
# -----------------------------# data sources assumed defined elsewhere
# data.azurerm_eventhub_namespace.ehns
# data.azurerm_eventhub.driver_messages
# data.azurerm_iothub.iothub   # IoT Hub must have SystemAssigned identity enabled

resource "azurerm_role_assignment" "iothub_eventhub_sender" {
  scope                = data.azurerm_eventhub.driver_messages.id  # or namespace id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = data.azurerm_iothub.iothub.identity[0].principal_id
}


# -----------------------------
# IoT Hub -> Event Hub endpoint (identity-based)
# NOTE: No connection_string. MSI is used.
# -----------------------------
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "EventHubMessages2"

  # NAMESPACE in URI; Event Hub in entity_path
  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name

  authentication_type = "identityBased"

  # Make sure the role assignment exists before the endpoint is created
  depends_on = [azurerm_role_assignment.iothub_eventhub_sender]
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

  lifecycle {
    replace_triggered_by = [
      azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.id
    ]
  }
}
