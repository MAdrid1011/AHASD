# Installation Guide

Setup instructions for AHASD simulator platform.

## 📋 System Requirements

### Minimum Requirements
- **OS**: Linux (Ubuntu 20.04+ recommended), macOS 10.15+
- **CPU**: 4 cores
- **RAM**: 8 GB
- **Disk**: 10 GB free space
- **Compiler**: GCC 7.0+ or Clang 10.0+ (C++17 support)

### Recommended
- **OS**: Ubuntu 22.04 LTS
- **CPU**: 8+ cores
- **RAM**: 16 GB
- **Disk**: 20 GB
- **Compiler**: GCC 11+

## 🔧 Dependencies

### System Dependencies

#### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  cmake \
  scons \
  git \
  python3 \
  python3-pip \
  libboost-all-dev \
  libeigen3-dev
```

#### macOS
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install dependencies
brew install cmake scons boost eigen python@3.11
```

#### CentOS/RHEL
```bash
sudo yum groupinstall -y "Development Tools"
sudo yum install -y cmake scons python3 python3-pip boost-devel eigen3-devel
```

### Python Dependencies

```bash
# Required packages
pip3 install numpy>=1.21.0 matplotlib>=3.5.0 pandas>=1.3.0

# Optional packages (for advanced analysis)
pip3 install seaborn scipy jupyter
```

### Verify Installation

```bash
# Check compiler version
g++ --version  # Should be 7.0 or higher
python3 --version  # Should be 3.8 or higher

# Check CMake
cmake --version  # Should be 3.16 or higher

# Check Python packages
python3 -c "import numpy, matplotlib, pandas; print('All packages installed')"
```

## 📦 Clone Repository

### Basic Clone

```bash
git clone https://github.com/yourusername/AHASD.git
cd AHASD
```

### With Submodules

```bash
git clone --recursive https://github.com/yourusername/AHASD.git
cd AHASD

# If already cloned without --recursive
git submodule update --init --recursive
```

### Verify Submodules

```bash
# Check submodule status
git submodule status

# Should show:
# <commit_hash> ONNXim (tag or branch)
# <commit_hash> PIMSimulator (tag or branch)
```

## 🏗️ Build ONNXim (NPU Simulator)

### Standard Build

```bash
cd ONNXim
mkdir -p build
cd build

# Configure
cmake .. \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_STANDARD=17

# Build (use all available cores)
make -j$(nproc)

# Verify build
ls -lh onnxim_simulator  # Should exist
./onnxim_simulator --help  # Should show help message
```

### Build Options

```bash
# Debug build (with symbols)
cmake .. -DCMAKE_BUILD_TYPE=Debug

# With specific compiler
cmake .. -DCMAKE_CXX_COMPILER=g++-11

# Install to custom location
cmake .. -DCMAKE_INSTALL_PREFIX=/opt/onnxim
make install
```

### Troubleshooting ONNXim Build

**Issue**: `fatal error: onnx/onnx_pb.h: No such file or directory`

```bash
# Install ONNX dependencies
cd ONNXim/extern/onnx
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install
```

**Issue**: Protobuf version mismatch

```bash
# Use bundled protobuf
cd ONNXim/extern/protobuf
./configure --prefix=$HOME/.local
make -j$(nproc)
make install
export PKG_CONFIG_PATH=$HOME/.local/lib/pkgconfig:$PKG_CONFIG_PATH
```

## 🏗️ Build PIMSimulator

### Standard Build

```bash
cd ../../PIMSimulator  # From AHASD root

# Build with scons
scons -j$(nproc)

# Verify build
ls -lh pimsim  # Should exist
./pimsim --help  # Should show help message
```

### Build Options

```bash
# Debug build
scons DEBUG=1

# With specific C++ version
scons CXX_STANDARD=17

# Clean and rebuild
scons -c
scons -j$(nproc)
```

### Troubleshooting PIMSimulator Build

**Issue**: `scons: command not found`

```bash
pip3 install scons
# Or
sudo apt-get install scons
```

**Issue**: Build warnings about FP16

```bash
# This is expected - the simulator includes half-precision support
# Warnings can be ignored unless they cause errors
```

## 🔗 Link AHASD Components

### Set Environment Variables

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
# AHASD environment
export AHASD_HOME=/path/to/AHASD
export ONNXIM_HOME=$AHASD_HOME/ONNXim
export PIM_SIM_HOME=$AHASD_HOME/PIMSimulator
export PATH=$ONNXIM_HOME/build:$PIM_SIM_HOME:$PATH
export PYTHONPATH=$AHASD_HOME/scripts:$PYTHONPATH

# Apply changes
source ~/.bashrc  # or source ~/.zshrc
```

### Verify Environment

```bash
echo $AHASD_HOME  # Should print /path/to/AHASD
which onnxim_simulator  # Should find the binary
which pimsim  # Should find the binary
```

## ✅ Verification

### Run Test Suite

```bash
cd $AHASD_HOME

# 1. Validate hardware costs
python3 scripts/validate_hardware_costs.py
# Expected: ✓ Claim VALIDATED (overhead = 2.51% < 3%)

# 2. Run quick demo
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc --enable-tvc --enable-aau \
  --output ./results/test

# 3. Check results
test -f results/test/metrics.txt && echo "✓ Demo completed successfully"
```

### Component Tests

```bash
# Test ONNXim
cd $ONNXIM_HOME/build
./onnxim_simulator --config ../configs/test.json

# Test PIMSimulator  
cd $PIM_SIM_HOME
./pimsim --config ini/HBM2_samsung_2M_16B_x64.ini

# Test AHASD integration
cd $AHASD_HOME
python3 -c "
from scripts.run_single_config import *
print('✓ All imports successful')
"
```

## 🐳 Docker Installation (Alternative)

If you prefer containerized installation:

```bash
# Build Docker image
docker build -t ahasd:latest .

# Run container
docker run -it --rm \
  -v $(pwd)/results:/workspace/results \
  ahasd:latest

# Inside container
python3 scripts/validate_hardware_costs.py
```

## 🎯 Post-Installation

### Download Model Files (Optional)

For running with actual models:

```bash
# Create models directory
mkdir -p $AHASD_HOME/models/weights

# Download example models (placeholder - add actual links)
# wget https://example.com/llama2-7b.onnx -O models/weights/llama2-7b.onnx
```

### Configure Paths

Edit `configs/ahasd_config_template.json` to set correct paths:

```json
{
  "paths": {
    "onnxim_binary": "$ONNXIM_HOME/build/onnxim_simulator",
    "pimsim_binary": "$PIM_SIM_HOME/pimsim",
    "model_dir": "$AHASD_HOME/models/weights"
  }
}
```

## 🔄 Updates

### Update AHASD

```bash
cd $AHASD_HOME
git pull
git submodule update --recursive
```

### Rebuild After Update

```bash
# Rebuild ONNXim
cd $ONNXIM_HOME/build
make clean
cmake ..
make -j$(nproc)

# Rebuild PIMSimulator
cd $PIM_SIM_HOME
scons -c
scons -j$(nproc)
```

## 🗑️ Uninstallation

```bash
# Remove AHASD directory
rm -rf $AHASD_HOME

# Remove environment variables from ~/.bashrc or ~/.zshrc
# (manually edit and remove AHASD section)

# Remove Python packages (optional)
pip3 uninstall numpy matplotlib pandas
```

## 📞 Getting Help

- **Build issues**: Check [Troubleshooting](#troubleshooting-onnxim-build)
- **Runtime issues**: See [Quick Start Guide](QuickStart.md#troubleshooting)
- **Questions**: Open an issue on [GitHub](https://github.com/yourusername/AHASD/issues)

## 📚 Next Steps

After successful installation:
1. Follow the [Quick Start Guide](QuickStart.md) to run your first experiment
2. Read [Configuration Guide](Configuration.md) to customize settings
3. Explore [Experiments](Experiments.md) to reproduce paper results

---

**Installation Time**: ~15-30 minutes (depending on system)

