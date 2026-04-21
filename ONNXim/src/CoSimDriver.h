#ifndef COSIM_DRIVER_H
#define COSIM_DRIVER_H
// B2.2 — Co-simulation driver.
//
// Thin facade that glues the PIMBackend into ONNXim's existing Simulator
// cycle loop. When `SimulationConfig::pim_enable` is false the driver is
// inert (`is_active()` returns false) and Simulator falls back to its legacy
// single-backend DRAM path.
//
// When active, Simulator forwards DRAM push/pop/cycle events through here so
// the PIM overlay can:
//   (1) record per-class traffic for B2.4 energy accounting,
//   (2) apply GTSU / TVC-driven per-channel stalls, and
//   (3) drive the new "AHASD Cycle Coupling: real_coupling" log line.

#include <memory>

#include "PIMBackend.h"

class CoSimDriver {
 public:
  explicit CoSimDriver(SimulationConfig config);

  bool is_active() const { return _pim && _pim->is_active(); }
  PIMBackend* pim() { return _pim.get(); }
  const PIMBackend* pim() const { return _pim.get(); }

  // Forwarded from Simulator's push/pop/cycle paths.
  uint32_t on_dram_push(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle);
  void on_dram_pop(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle);
  void cycle(uint64_t npu_cycle);

  // End-of-simulation summary printer.
  void print_statistics(uint64_t final_npu_cycle) const;

 private:
  std::unique_ptr<PIMBackend> _pim;
};

#endif
