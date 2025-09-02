# ---------------------------------------------
# RBAC: IoT Hub MI -> EH Sender
# ---------------------------------------------
resource "azurerm_role_assignment" "iothub_eventhub_sender" {
  scope                = azurerm_eventhub.eventhub_driver_messages.id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = data.azurerm_iothub.iothub.identity[0].principal_id
}

# ---------------------------------------------
# IoT Hub -> Event Hub endpoint (Managed Identity)
# ---------------------------------------------
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "SqlIngestionToEvents2"

  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name
  authentication_type = "identityBased"

  depends_on = [
    azurerm_role_assignment.iothub_eventhub_sender
  ]
}

# ---------------------------------------------
# Route: DeviceMessages("Raw") -> custom EH endpoint
# ---------------------------------------------
resource "azurerm_iothub_route" "telemetry_to_custom_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToEvents2"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name]
  enabled        = true

  depends_on = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages]
}
