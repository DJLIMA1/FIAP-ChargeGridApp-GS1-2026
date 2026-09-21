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
  Reading read(bool charging, unsigned long elapsedMs);
 private:
  float energyWh = 0;
};
