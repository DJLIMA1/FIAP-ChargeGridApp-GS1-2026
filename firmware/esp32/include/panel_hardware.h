#pragma once

// O profile da placa inicializa LVGL, RGB LCD e touch, registra display/indev e
// só então retorna true. Não implemente pinagem sem conferir o modelo exato.
bool chargegridPanelHardwareSetup();
// Diagnostic framebuffer capture; call only while idle, never during a session.
bool chargegridPanelCapture();
