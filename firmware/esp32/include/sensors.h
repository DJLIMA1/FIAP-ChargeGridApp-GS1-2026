#pragma once
struct Reading {
  float socPercent;
  float energyWh;
  float powerW;
  bool connected;
};
class SimulatedSensors {
 public:
  void start();
  // powerW: potência simulada (nominal 7,2 kW ou o limite max_power_kw do START).
  Reading read(bool charging, unsigned long elapsedMs, float powerW = 7200.0f);
 private:
  float energyWh = 0;
};
