
# -----------------------------
# IoT Hub -> Event Hub endpoint (identity-based)
# NOTE: No connection_string needed. Uses IoT Hub's MSI.
# -----------------------------
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = local.endpoint_name

  # NAMESPACE in URI; Event Hub in entity_path
  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name

  authentication_type = "identityBased"

  # Make sure the RBAC assignment is effective first
  depends_on = [
    azurerm_role_assignment.iothub_eventhub_sender
  ]
}

# -----------------------------
# Route DeviceMessages -> the custom EH endpoint
# -----------------------------
resource "azurerm_iothub_route" "telemetry_to_custom_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = local.endpoint_name

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"
  endpoint_names = [local.endpoint_name]
  enabled        = true

  depends_on = [
    azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages
  ]
}
