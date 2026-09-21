#pragma once
// Copie para chargegrid_config.h (ignorado pelo Git). Uma chave por dispositivo.
#define WIFI_SSID "YOUR_WIFI"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define API_BASE_URL "https://your-api.example"
#define DEVICE_KEY "YOUR_INDIVIDUAL_DEVICE_KEY"
// Cole o certificado raiz PEM da cadeia do servidor. Nunca desative TLS.
static const char ROOT_CA[] = R"PEM(-----BEGIN CERTIFICATE-----
REPLACE_WITH_SERVER_ROOT_CA
-----END CERTIFICATE-----)PEM";
