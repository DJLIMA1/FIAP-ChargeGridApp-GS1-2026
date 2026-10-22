#pragma once
// Todos os textos fixos do totem (pt-BR). O design troca só este arquivo, ui/tokens.h,
// widgets.cpp e view_*.cpp. Papel: TITLE vai para as fontes Barlow Bold (só ASCII e
// ÁÀÂÃÇÉÊÍÓÔÕÚ áàâãçéêíóôõú), BODY para as Barlow Medium (U+0020-U+00FF e U+2022).
// Nunca usar "—", "–", "…", "→", "≈", "✓" nem "·" nos títulos; o teste de cobertura de
// glifos (tools/tests/firmware_behavior.cpp) percorre esta tabela e as telas renderizadas.
namespace kiosk {
namespace str {
enum Role { TITLE, BODY };

#define CG_KIOSK_STRINGS(X)                                                                  \
  X(kStartButton, TITLE, "Iniciar recarga")                                                    \
  X(kStartHint, BODY, "Pague aqui mesmo, sem app. Ou use o código ao lado no app ChargeGrid.") \
  X(kCodeCaption, BODY, "TEM O APP? CÓDIGO")                                                 \
  X(kChooseTitle, TITLE, "Defina sua recarga")                                           \
  X(kChooseCable, BODY, "Conecte o cabo ao carro antes de pagar.")                            \
  X(kModeValue, TITLE, "Por valor")                                                          \
  X(kModeTime, TITLE, "Por tempo")                                                           \
  X(kModeEnergy, TITLE, "Por energia")                                                       \
  X(kModeValueHint, BODY, "Escolha quanto pagar (R$)")                                        \
  X(kModeTimeHint, BODY, "Escolha os minutos")                                                \
  X(kModeEnergyHint, BODY, "Escolha os kWh")                                                  \
  X(kAmountValueTitle, TITLE, "Quanto você quer pagar?")                                     \
  X(kAmountTimeTitle, TITLE, "Quanto tempo?")                                                \
  X(kAmountEnergyTitle, TITLE, "Quanta energia?")                                            \
  X(kOtherValue, TITLE, "Outro valor")                                                       \
  X(kKeypadOk, TITLE, "Continuar")                                                                  \
  X(kKeypadClear, TITLE, "Limpar")                                                           \
  X(kEstimatePrefix, BODY, "Estimativa: ")                                                   \
  X(kEstimateNote, BODY, "Estimativa local. O valor final vem do servidor.")                  \
  X(kReviewTitle, TITLE, "Revise e aceite")                                                  \
  X(kAccept, TITLE, "Aceitar e pagar")                                                       \
  X(kBack, TITLE, "Voltar")                                                                  \
  X(kCancel, TITLE, "Cancelar")                                                              \
  X(kRetry, TITLE, "Tentar de novo")                                                         \
  X(kContinue, TITLE, "Continuar")                                                           \
  X(kDone, TITLE, "Concluir")                                                                \
  X(kStop, TITLE, "Encerrar")                                                                \
  X(kYes, TITLE, "Sim, encerrar")                                                            \
  X(kNo, TITLE, "Não")                                                                       \
  X(kDisconnect, TITLE, "Desconectar")                                                       \
  X(kStillThereTitle, TITLE, "Ainda está aí?")                                               \
  X(kStillThereDetail, BODY, "Toque em Continuar para não perder o que escolheu.")            \
  X(kMetricPrice, BODY, "PREÇO TRAVADO")                                                     \
  X(kMetricCap, BODY, "VALOR MÁXIMO")                                                        \
  X(kMetricEnergyEst, BODY, "ESTIMATIVA")                                                    \
  X(kMetricTimeEst, BODY, "TEMPO MÁXIMO")                                                    \
  X(kMetricOverstay, BODY, "PERMANÊNCIA")                                                    \
  X(kMetricEnergy, BODY, "ENERGIA")                                                          \
  X(kMetricPower, BODY, "POTÊNCIA")                                                          \
  X(kMetricCost, BODY, "VALOR / TETO")                                                       \
  X(kMetricTime, BODY, "TEMPO")                                                              \
  X(kMetricBattery, BODY, "BATERIA")                                                         \
  X(kMetricTotal, BODY, "TOTAL")                                                             \
  X(kMetricReturned, BODY, "DEVOLVIDO")                                                      \
  X(kMetricReceipt, BODY, "RECIBO")                                                          \
  X(kPayTitle, TITLE, "Pagamento")                                                           \
  X(kPayStripeHint, BODY, "Escaneie o QR com a câmera do celular e pague na página segura.")  \
  X(kPayStripeCaption, BODY, "Pagamento seguro pelo QR")                                      \
  X(kPayWaiting, BODY, "Aguardando a confirmação do pagamento")                               \
  X(kPayDeclined, BODY, "Pagamento recusado. Tente de novo pelo QR.")                         \
  X(kPaySimHint, BODY, "Confirme o pagamento para iniciar a recarga.")                        \
  X(kPayCreating, BODY, "Gerando o pagamento")                                               \
  X(kStartingTitle, TITLE, "Pagamento confirmado")                                           \
  X(kStartingDetail, BODY, "Iniciando a recarga. Mantenha o cabo conectado.")                \
  X(kStartFailedTitle, TITLE, "Não foi possível iniciar")                                   \
  X(kStartFailedDetail, BODY, "O valor foi devolvido. Nada foi cobrado.")                     \
  X(kLiveTitle, TITLE, "Recarga em andamento")                                               \
  X(kLivePaused, TITLE, "Recarga pausada")                                                   \
  X(kLiveHint, BODY, "Para parar antes, toque em Encerrar.")                                  \
  X(kConfirmTitle, TITLE, "Encerrar a recarga?")                                             \
  X(kConfirmDetail, BODY, "A recarga para agora e você paga só a energia usada.")             \
  X(kConfirmAppTitle, TITLE, "Encerrar a recarga do app?")                                   \
  X(kConfirmAppDetail, BODY, "Esta recarga foi iniciada pelo app. Ela para agora.")           \
  X(kReceiptTitle, TITLE, "Recarga concluída")                                               \
  X(kReceiptFull, TITLE, "Bateria cheia")                                                    \
  X(kReceiptCost, TITLE, "Valor máximo atingido")                                            \
  X(kReceiptTime, TITLE, "Tempo encerrado")                                                  \
  X(kReceiptOffline, TITLE, "Recarga parada por segurança")                                  \
  X(kReceiptOfflineDetail, BODY, "Sem conexão. Recibo em conferência.")                       \
  X(kReceiptPending, BODY, "Calculando o recibo")                                             \
  X(kReceiptFinal, BODY, "Escaneie para ver o recibo completo.")                             \
  X(kReceiptQrCaption, BODY, "Recibo completo")                                               \
  X(kSimulatedNoCharge, BODY, "Sem cobrança")                                                 \
  X(kVerifyingTitle, TITLE, "Verificando pagamento")                                         \
  X(kVerifyingDetail, BODY, "Aguarde. O servidor confirma o seu pedido.")                     \
  X(kVerifyingOffline, BODY, "Sem conexão. Seu pedido está guardado no servidor.")            \
  X(kOfflineTitle, TITLE, "Sem conexão")                                                     \
  X(kOfflineDetail, BODY, "Voltamos ao início. Nada foi cobrado.")                            \
  X(kAppStartedTitle, TITLE, "Ponto iniciado pelo app")                                      \
  X(kAppStartedDetail, BODY, "Este ponto acabou de ser iniciado pelo app. Nada foi cobrado.") \
  X(kReservedTitle, TITLE, "Ponto reservado")                                                \
  X(kReservedDetail, BODY, "Este ponto acabou de ser reservado pelo app.")                    \
  X(kBusyTitle, TITLE, "Ponto indisponível")                                                 \
  X(kBusyDetail, BODY, "Este ponto não pode iniciar agora. Encontre outro no app.")           \
  X(kInUseDetail, BODY, "Ponto em uso no momento. Nada foi cobrado.")                         \
  X(kUnavailableTitle, TITLE, "Totem indisponível")                                          \
  X(kUnavailableDetail, BODY, "Use o app ChargeGrid com o código do ponto.")                  \
  X(kCanceledTitle, TITLE, "Pedido cancelado")                                               \
  X(kCanceledDetail, BODY, "O pagamento volta inteiro. Nada foi cobrado.")                    \
  X(kNetworkError, BODY, "Sem resposta do servidor. Tente de novo.")                          \
  X(kOrderError, BODY, "Não foi possível criar o pedido. Tente de novo.")                     \
  X(kQuoteChanged, BODY, "O preço mudou. Confira o novo valor.")                              \
  X(kOutOfRange, BODY, "Valor fora do limite: ")                                              \
  X(kLoading, BODY, "Um instante")

#define CG_KIOSK_STRING_CONST(name, role, text) constexpr const char* name = text;
CG_KIOSK_STRINGS(CG_KIOSK_STRING_CONST)
#undef CG_KIOSK_STRING_CONST

struct Entry { const char* name; Role role; const char* text; };
#define CG_KIOSK_STRING_ENTRY(name, role, text) {#name, role, text},
constexpr Entry kAll[] = {CG_KIOSK_STRINGS(CG_KIOSK_STRING_ENTRY)};
#undef CG_KIOSK_STRING_ENTRY
constexpr size_t kCount = sizeof(kAll) / sizeof(kAll[0]);
}  // namespace str
}  // namespace kiosk
