#include "BiasAct.h"
#include "../Model.h"

#include <algorithm>
#include <cctype>
#include <stdexcept>

static const std::map<std::string, Opcode> activation_map = {
    {"gelu", Opcode::GELU},
    {"relu", Opcode::COMP},
    {"silu", Opcode::SWISH},
    {"swish", Opcode::SWISH},
    {"swiglu", Opcode::SWISH},
    {"softmax", Opcode::SOFTMAX},
};

static std::string normalize_activation(std::string activation) {
    activation.erase(
        activation.begin(),
        std::find_if(activation.begin(), activation.end(), [](unsigned char ch) {
            return !std::isspace(ch);
        }));
    activation.erase(
        std::find_if(activation.rbegin(), activation.rend(), [](unsigned char ch) {
            return !std::isspace(ch);
        }).base(),
        activation.end());
    std::transform(activation.begin(), activation.end(), activation.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return activation;
}

static Opcode resolve_activation(std::string activation) {
    std::string normalized = normalize_activation(activation);
    auto it = activation_map.find(normalized);
    if (it != activation_map.end()) {
        return it->second;
    }
    if (normalized.find("swiglu") != std::string::npos ||
        normalized.find("silu") != std::string::npos ||
        normalized.find("swish") != std::string::npos) {
        return Opcode::SWISH;
    }
    throw std::out_of_range("unsupported BiasAct activation: " + activation);
}

BiasAct::BiasAct(SimulationConfig config, Model* model,
               onnx::NodeProto& node_proto, uint32_t target_core)
    : Operation(config, model, node_proto, target_core) {

    /* Load weight info from node */
    _input_shape = get_input(0)->get_dims();
    _bias_shape = get_input(1)->get_dims();

    assert(_input_shape.size()==3);
    _batch_size = _input_shape.at(0);
    _seq = _input_shape.at(1);
    _dk = _input_shape.at(2);

    _output_shape = _input_shape;
    Tensor* pre_defind_tensor = _model->find_tensor(node_proto.output(0));
    if (pre_defind_tensor == nullptr) {
        std::unique_ptr<Tensor> output_tensor = std::make_unique<Tensor>(
            _id, node_proto.output(0), _output_shape, _config.precision, false);
            _outputs.push_back(output_tensor.get()->get_id());
        _model->add_tensor(std::move(output_tensor));
    } else {
        pre_defind_tensor->redefine_tensor(_id, _output_shape);
    }
}

BiasAct::BiasAct(SimulationConfig config, Model* model,
               std::string name, std::map<std::string, std::string> &attributes, uint32_t target_core)
    : Operation(config, model, name, attributes, target_core) {
    _activation = resolve_activation(get_attribute("activation"));
    _use_bias = std::stoi(get_attribute("has_bias"));
    auto llama_mlp = _attributes.find("llama_mlp");
    _llama_mlp = llama_mlp == _attributes.end() ? 0 : std::stoi(llama_mlp->second);
}

void BiasAct::initialize_tiles(MappingTable& mapping_table) {
    if(_outputs.size() == 0) {
        _input_shape = get_input(0)->get_dims();
        _output_shape = _input_shape;
        if(_llama_mlp)
            _output_shape[1] = _input_shape[1] / 2;
        auto output_tensor = std::make_unique<Tensor>(_id, name_gen(_name, "output"), _output_shape, _config.precision, false);
        _outputs.push_back(output_tensor.get()->get_id());
        _model->add_tensor(std::move(output_tensor));
        _dk = _input_shape.at(1);
        _seq = _input_shape.at(0);
        _batch_size = 1;
    }
    calculate_loops();
    for (uint32_t tokens= 0; tokens<_seq*_batch_size; tokens+=_tokens_per_tile) {
        uint32_t remain_tokens = std::min(_seq*_batch_size-tokens, _tokens_per_tile);
        std::unique_ptr<Tile> tile = std::make_unique<Tile>(Tile{
            .status = Tile::Status::INITIALIZED,
            .optype = get_name(),
            .layer_id = _id,
            .accum = false,
        });
        /* dummy mapping */
        Mapping mapping;
        _tiles.push_back(std::move(tile));
        initialize_instructions(_tiles.back().get(), mapping, tokens, remain_tokens);

    }
}

void BiasAct::initialize_instructions(Tile* tile, Mapping mapping, uint32_t token_offset, uint32_t tokens) {
    addr_type sram_base = SPAD_BASE;
    addr_type sram_bias_base = sram_base + tokens * _dk * _config.precision;

    addr_type first_addr, output_addr;
    first_addr = get_operand_addr(_INPUT_OPERAND);
    output_addr = get_operand_addr(_OUTPUT_OPERAND);
    /* Load two tile (input: tokens x _dk, skip: tokens x _dk) */
    std::set<addr_type> dram_addrs;
    std::set<addr_type> dram_output_addrs;
    std::set<addr_type> dram_skip_addrs;
    for (int offset=0; offset<tokens*_dk*_config.precision; offset+=_config.dram_req_size) {
        dram_addrs.insert(first_addr + token_offset*_dk*_config.precision + offset);
        dram_output_addrs.insert(output_addr + token_offset*_dk*_config.precision + offset);
    }

    if (_use_bias) {
        addr_type second_addr = get_operand_addr(_INPUT_OPERAND+1);
        for (int offset=0; offset<_dk*_config.precision; offset+=_config.dram_req_size) {
            dram_skip_addrs.insert(second_addr + _seq*_dk*_config.precision + offset);
        }
    }


    tile->instructions.push_back(std::make_unique<Instruction>(Instruction{
        .opcode = Opcode::MOVIN,
        .dest_addr = sram_base,
        .size = (uint32_t)dram_addrs.size(),
        .src_addrs = std::vector<addr_type>(dram_addrs.begin(), dram_addrs.end()),
        .operand_id = _INPUT_OPERAND,  // query
    }));

    if (_use_bias) {
        tile->instructions.push_back(std::make_unique<Instruction>(Instruction{
            .opcode = Opcode::MOVIN,
            .dest_addr = sram_bias_base,
            .size = (uint32_t)dram_skip_addrs.size(),
            .src_addrs = std::vector<addr_type>(dram_skip_addrs.begin(), dram_skip_addrs.end()),
            .operand_id = _INPUT_OPERAND+1,  // bias
        }));

        tile->instructions.push_back(std::make_unique<Instruction>(Instruction{
            .opcode = Opcode::ADD,
            .dest_addr = sram_base,
            .size = _dk * tokens * _config.precision / _config.dram_req_size,
            .compute_size = _dk * tokens * _config.precision,
            .src_addrs = std::vector<addr_type>{sram_base, sram_bias_base},
        }));
    }

    tile->instructions.push_back(std::make_unique<Instruction>(Instruction{
        .opcode = _activation,
        .dest_addr = sram_base,
        .size = _output_shape[1] * tokens * _config.precision / _config.dram_req_size,
        .compute_size = _output_shape[1] * tokens * _config.precision,
        .src_addrs = std::vector<addr_type>{sram_base},
    }));
    if(_llama_mlp) {
        tile->instructions.push_back(std::make_unique<Instruction>(Instruction{
            .opcode = Opcode::MUL,
            .dest_addr = sram_base,
            .size = _output_shape[1] * tokens * _config.precision / _config.dram_req_size,
            .compute_size = _output_shape[1] * tokens * _config.precision,
            .src_addrs = std::vector<addr_type>{sram_base},
        }));
    }
    tile->instructions.push_back(std::make_unique<Instruction>(Instruction{
        .opcode = Opcode::MOVOUT,
        .dest_addr = sram_base,
        .size = (uint32_t)dram_output_addrs.size(),
        .src_addrs = std::vector<addr_type>(dram_output_addrs.begin(), dram_output_addrs.end()),
        .operand_id = _OUTPUT_OPERAND,
    }));
}

void BiasAct::calculate_loops() {
    uint32_t size_per_token = _dk * _config.precision;
    uint32_t sram_capacity = _config.core_config[target_core].spad_size KB / 2;  // unit: byte

    _tokens_per_tile = (sram_capacity / size_per_token) - 1; 
    assert (_tokens_per_tile >= 1);
    if (_tokens_per_tile > _seq * _batch_size) _tokens_per_tile = _seq * _batch_size;
    int num_tiles = ceil_div(_seq, _tokens_per_tile);
    if(num_tiles < _config.num_cores * 2) {
        _tokens_per_tile = ceil_div(_seq, _config.num_cores * 2);
        num_tiles = ceil_div(_seq, _tokens_per_tile);
    }
    spdlog::info("[BiasAct] tokens_per_tile: {}", _tokens_per_tile);
}
