#include "Common.h"

uint32_t generate_id() {
  static uint32_t id_counter{0};
  return id_counter++;
}
uint32_t generate_mem_access_id() {
  static uint32_t id_counter{0};
  return id_counter++;
}

addr_type allocate_address(uint32_t size) {
  static addr_type base_addr{0};
  addr_type result = base_addr;
  int offset = 0;
  if (result % 256 != 0) {
    offset = 256 - (result % 256);
  }
  result += offset;
  assert(result % 256 == 0);
  base_addr += (size + offset);
  base_addr += (256 - base_addr % 256);
  return result;
}

template <typename T>
T get_config_value(json config, std::string key) {
  if (config.contains(key)) {
    return config[key];
  } else {
    throw std::runtime_error(fmt::format("Config key {} not found", key));
  }
}

const static std::map<std::string, CoreType> core_type_map = {
  {"systolic_os", CoreType::SYSTOLIC_OS},
  {"systolic_ws", CoreType::SYSTOLIC_WS}
};

const static std::map<std::string, DramType> dram_type_map = {
  {"simple", DramType::SIMPLE},
  {"ramulator", DramType::RAMULATOR1},
  {"ramulator2", DramType::RAMULATOR2}
};

const static std::map<std::string, IcntType> icnt_type_map = {
  {"simple", IcntType::SIMPLE},
  {"booksim2", IcntType::BOOKSIM2}
};

SimulationConfig initialize_config(json config) {
  SimulationConfig parsed_config;

  /* Core configs */
  parsed_config.num_cores = get_config_value<uint32_t>(config, "num_cores");
  parsed_config.core_config = new struct CoreConfig[parsed_config.num_cores];
  parsed_config.core_freq = get_config_value<uint32_t>(config, "core_freq");
  parsed_config.core_print_interval = get_config_value<uint32_t>(config, "core_print_interval");

  for (int i=0; i<parsed_config.num_cores; i++) {
    std::string core_id = "core_" + std::to_string(i);
    auto core_config = config["core_config"][core_id];
    std::string core_type = core_config["core_type"];
    if (core_type_map.contains(core_type)) {
      parsed_config.core_config[i].core_type = core_type_map.at(core_type);
    } else {
      throw std::runtime_error(fmt::format("Not implemented core type {} ", core_type));
    }
    parsed_config.core_config[i].core_width = core_config["core_width"];
    parsed_config.core_config[i].core_height = core_config["core_height"];

    /* Vector configs */
    parsed_config.core_config[i].vector_process_bit = core_config["vector_process_bit"];
    parsed_config.core_config[i].add_latency = core_config["add_latency"];
    parsed_config.core_config[i].mul_latency = core_config["mul_latency"];
    parsed_config.core_config[i].exp_latency = core_config["exp_latency"];
    parsed_config.core_config[i].gelu_latency = core_config["gelu_latency"];
    parsed_config.core_config[i].add_tree_latency = core_config["add_tree_latency"];
    parsed_config.core_config[i].scalar_sqrt_latency = core_config["scalar_sqrt_latency"];
    parsed_config.core_config[i].scalar_add_latency = core_config["scalar_add_latency"];
    parsed_config.core_config[i].scalar_mul_latency = core_config["scalar_mul_latency"];
    parsed_config.core_config[i].mac_latency = core_config["mac_latency"];
    parsed_config.core_config[i].div_latency = core_config["div_latency"];

    /* SRAM configs */
    parsed_config.core_config[i].sram_width = core_config["sram_width"];
    parsed_config.core_config[i].spad_size = core_config["spad_size"];
    parsed_config.core_config[i].accum_spad_size = core_config["accum_spad_size"];
  }

  /* DRAM config */
  std::string dram_type = get_config_value<std::string>(config, "dram_type");
  if (dram_type_map.contains(dram_type)) {
    parsed_config.dram_type = dram_type_map.at(dram_type);
  } else {
    throw std::runtime_error(fmt::format("Not implemented dram type {} ", dram_type));
  }

  parsed_config.dram_freq = get_config_value<uint32_t>(config, "dram_freq");
  if (config.contains("dram_latency"))
    parsed_config.dram_latency = config["dram_latency"];
  if (config.contains("dram_config_path"))
    parsed_config.dram_config_path = config["dram_config_path"];
  parsed_config.dram_channels = config["dram_channels"];
  if (config.contains("dram_req_size"))
    parsed_config.dram_req_size = config["dram_req_size"];
  if (config.contains("dram_print_interval"))
    parsed_config.dram_print_interval = config["dram_print_interval"];
  if(config.contains("dram_nbl"))
    parsed_config.dram_nbl = config["dram_nbl"];
  if (config.contains("dram_size"))
    parsed_config.dram_size = config["dram_size"];
  else
    parsed_config.dram_size = 0;

  /* Icnt config */
  std::string icnt_type = get_config_value<std::string>(config, "icnt_type");
  if (icnt_type_map.contains(icnt_type)) {
    parsed_config.icnt_type = icnt_type_map.at(icnt_type);
  } else {
    throw std::runtime_error(fmt::format("Not implemented icnt type {} ", icnt_type));
  }

  parsed_config.icnt_freq = get_config_value<uint32_t>(config, "icnt_freq");
  if (config.contains("icnt_latency"))
    parsed_config.icnt_latency = config["icnt_latency"];
  if (config.contains("icnt_config_path"))
    parsed_config.icnt_config_path = config["icnt_config_path"];
  if (config.contains("icnt_print_interval"))
    parsed_config.icnt_print_interval = config["icnt_print_interval"];

  parsed_config.scheduler_type = get_config_value<std::string>(config, "scheduler");
  parsed_config.precision = get_config_value<uint32_t>(config, "precision");
  parsed_config.layout = get_config_value<std::string>(config, "layout");

  /* AHASD config */
  if (config.contains("enable_ahasd"))
    parsed_config.enable_ahasd = config["enable_ahasd"];
  if (config.contains("enable_edc"))
    parsed_config.enable_edc = config["enable_edc"];
  if (config.contains("enable_tvc"))
    parsed_config.enable_tvc = config["enable_tvc"];
  if (config.contains("enable_aau"))
    parsed_config.enable_aau = config["enable_aau"];
  if (config.contains("max_draft_length"))
    parsed_config.max_draft_length = config["max_draft_length"];
  // B2.3 — SSRC config keys (enable_ssrc, enable_ssrc_proxy, enable_ssrc_trace,
  // ssrc_state_bytes_per_token, ssrc_resident_limit_bytes,
  // ssrc_confidence_threshold) were removed when the sidecar was deleted.
  // Older onnxim_config.json inputs may still carry them; json::parse ignores
  // unknown keys so no compatibility shim is required.

  /* B2.2 — PIM co-simulation config */
  if (config.contains("pim_enable"))
    parsed_config.pim_enable = config["pim_enable"];
  if (config.contains("pim_channel_mask"))
    parsed_config.pim_channel_mask = config["pim_channel_mask"].get<std::string>();
  if (config.contains("pim_channel_stride"))
    parsed_config.pim_channel_stride = config["pim_channel_stride"];
  if (config.contains("pim_clock_mhz"))
    parsed_config.pim_clock_mhz = config["pim_clock_mhz"];
  if (config.contains("pim_enable_aau_fusion"))
    parsed_config.pim_enable_aau_fusion = config["pim_enable_aau_fusion"];
  if (config.contains("pim_aau_fusion_ratio"))
    parsed_config.pim_aau_fusion_ratio = config["pim_aau_fusion_ratio"];
  if (config.contains("pim_gtsu_switch_ns"))
    parsed_config.pim_gtsu_switch_ns = config["pim_gtsu_switch_ns"];

  /* B2.4 — energy model coefficients (LUT, per pJ). All optional. */
  if (config.contains("energy_npu_active_pj_per_cycle"))
    parsed_config.energy_npu_active_pj_per_cycle = config["energy_npu_active_pj_per_cycle"];
  if (config.contains("energy_npu_vector_pj_per_cycle"))
    parsed_config.energy_npu_vector_pj_per_cycle = config["energy_npu_vector_pj_per_cycle"];
  if (config.contains("energy_npu_idle_pj_per_cycle"))
    parsed_config.energy_npu_idle_pj_per_cycle = config["energy_npu_idle_pj_per_cycle"];
  if (config.contains("energy_pim_read_pj_per_byte"))
    parsed_config.energy_pim_read_pj_per_byte = config["energy_pim_read_pj_per_byte"];
  if (config.contains("energy_pim_write_pj_per_byte"))
    parsed_config.energy_pim_write_pj_per_byte = config["energy_pim_write_pj_per_byte"];
  if (config.contains("energy_pim_rank_leak_pj_per_pim_cycle"))
    parsed_config.energy_pim_rank_leak_pj_per_pim_cycle = config["energy_pim_rank_leak_pj_per_pim_cycle"];
  if (config.contains("energy_aau_fusion_save_pj_per_event"))
    parsed_config.energy_aau_fusion_save_pj_per_event = config["energy_aau_fusion_save_pj_per_event"];
  if (config.contains("energy_bus_pj_per_byte"))
    parsed_config.energy_bus_pj_per_byte = config["energy_bus_pj_per_byte"];
  if (config.contains("energy_gtsu_switch_pj_per_event"))
    parsed_config.energy_gtsu_switch_pj_per_event = config["energy_gtsu_switch_pj_per_event"];

  if (config.contains("partition")) {
    for (int i=0; i<parsed_config.num_cores; i++) {
      std::string core_partition = "core_" + std::to_string(i);
      uint32_t partition_id = uint32_t(config["partition"][core_partition]);
      parsed_config.partiton_map[partition_id].push_back(i);
      spdlog::info("CPU {}: Partition {}", i, partition_id);
    }
  } else {
    /* Default: all partition 0 */
    for (int i=0; i<parsed_config.num_cores; i++) {
      parsed_config.partiton_map[0].push_back(i);
      spdlog::info("CPU {}: Partition {}", i, 0);
    }
  }
  return parsed_config;
}

uint32_t ceil_div(uint32_t src, uint32_t div) { return (src+div-1)/div; }

std::vector<uint32_t> parse_dims(const std::string &str) {
  std::vector<uint32_t> dims;
  std::string token;
  std::istringstream tokenStream(str);
  while (std::getline(tokenStream, token, ',')) {
      dims.push_back(std::stoi(token));
  }
  return dims;
}

std::string dims_to_string(const std::vector<uint32_t> &dims){
  std::string str;
  for (int i=0; i<dims.size(); i++) {
    str += std::to_string(dims[i]);
    if (i != dims.size()-1) {
      str += ",";
    }
  }
  return str;
}
