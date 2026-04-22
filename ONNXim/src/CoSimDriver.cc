// B2.2 — CoSimDriver implementation. See CoSimDriver.h for rationale.

#include "CoSimDriver.h"

CoSimDriver::CoSimDriver(SimulationConfig config)
    : _pim(std::make_unique<PIMBackend>(config)) {}

uint32_t CoSimDriver::on_dram_push(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle) {
  if (!_pim) return 0;
  return _pim->on_dram_push(cid, req, npu_cycle);
}

bool CoSimDriver::try_aau_bypass(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle) {
  if (!_pim) return false;
  return _pim->try_aau_bypass(cid, req, npu_cycle);
}

void CoSimDriver::on_dram_pop(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle) {
  if (!_pim) return;
  _pim->on_dram_pop(cid, req, npu_cycle);
}

void CoSimDriver::cycle(uint64_t npu_cycle) {
  if (!_pim) return;
  _pim->cycle(npu_cycle);
}

void CoSimDriver::print_statistics(uint64_t final_npu_cycle) const {
  if (!_pim) return;
  _pim->print_statistics(final_npu_cycle);
}
