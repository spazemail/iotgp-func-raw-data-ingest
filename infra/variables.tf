variable "app_acronym" {
  description = "Application's acronym on CMDB"
  type        = string
}

variable "app_insights_enabled" {
  description = "Turn on application insights"
  type        = string
}

variable "function_name" {
  description = "Az function name"
  type        = string
}

variable "artifact_zip" {
  description = "Artifacts zip file"
  type        = string
}

variable "seq_number" {
  description = "Sequencial number"
  type        = string
  default     = "01"
}

variable "location" {
  description = "The Azure Region in which all resources for this Load Balancer should be provisioned"
  type        = string
  default     = "West Europe"
}

variable "location_acronym" {
  description = "The Azure Region acronym to be part of the resources name"
  type        = string
  default     = "we"
}

variable "environment" {
  description = "Identify the environment for the specific workload"
  type        = string
}

variable "resource_group" {
  description = "The resource group name"
  type        = string
}

variable "subscription_id" {
  description = "Azure Subscription Id"
  type        = string
}

variable "storage_account_name" {
  description = "Main storage account"
  type        = string
}

variable "storage_container_name" {
  description = "Name of the container to upload function zip"
  type        = string
}

variable "eventhubs_namespace" {
  description = "The event hubs namespace name"
  type        = string
}

variable "log_analytics_name" {
  description = "Log analytics name"
  type        = string
}

variable "function_service_plan_name" {
  description = "Name of the existing service plan for functions"
  type        = string
}

variable "build_number" {
  description = "Build number"
  type        = string
  default     = "0.0.1"
}

variable "iothub_name" {
  description = "Identify the existing iot hub"
}