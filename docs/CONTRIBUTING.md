# Contributing to AHASD

Thank you for your interest in contributing to AHASD! This document provides guidelines for contributing.

## 🤝 Ways to Contribute

- 🐛 **Bug Reports**: Report issues you encounter
- ✨ **Feature Requests**: Suggest new features or improvements
- 📝 **Documentation**: Improve or translate documentation
- 🔧 **Code**: Fix bugs or implement features
- 🧪 **Testing**: Add tests or improve coverage
- 📊 **Benchmarks**: Add new models or algorithms

## 🚀 Getting Started

### 1. Fork the Repository

```bash
# Fork on GitHub, then clone your fork
cd AHASD
git remote add upstream https://github.com/original/AHASD.git
```

### 2. Set Up Development Environment

```bash
# Install dependencies
pip3 install -r requirements.txt
pip3 install -r requirements-dev.txt  # Development dependencies

# Build simulators
cd ONNXim && mkdir build && cd build && cmake .. && make
cd ../../PIMSimulator && scons
```

### 3. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

## 📝 Code Guidelines

### C++ Code Style

Follow the existing code style in the project:

```cpp
// Use meaningful names
class EntropyHistoryControl {  // Good
    bool should_continue_drafting();
};

// Not
class EHC {  // Bad
    bool scd();
};

// Comments for complex logic
// Calculate PHT index from entropy groups and LLR
uint16_t pht_index = (avg_high << 6) | (avg_low << 3) | llr_;

// Document public APIs
/**
 * Decides whether to continue look-ahead drafting.
 * 
 * @param avg_entropy Average entropy of current draft batch
 * @return true if should continue, false otherwise
 */
bool should_continue_drafting(float avg_entropy);
```

### Python Code Style

Follow PEP 8:

```python
# Use type hints
def analyze_results(results_dir: str) -> Dict[str, float]:
    """Analyze simulation results from directory."""
    pass

# Descriptive variable names
throughput_tokens_per_sec = calculate_throughput(cycles, tokens)  # Good
tp = calc_tp(c, t)  # Bad

# Document functions
def run_simulation(config: Dict, output_dir: str) -> bool:
    """
    Run AHASD simulation with given configuration.
    
    Args:
        config: Configuration dictionary
        output_dir: Output directory path
        
    Returns:
        True if successful, False otherwise
    """
    pass
```

### Documentation Style

- Use clear, concise language
- Include code examples
- Add diagrams where helpful
- Keep README up to date

## 🧪 Testing

### Running Tests

```bash
# Run all tests
python3 -m pytest tests/

# Run specific test
python3 -m pytest tests/test_edc.py

# With coverage
python3 -m pytest --cov=src tests/
```

### Adding Tests

```python
# tests/test_edc.py
import pytest
from src.async_queue.EDC import EDC

def test_entropy_to_bucket():
    """Test entropy mapping to buckets."""
    edc = EDC()
    assert edc.entropy_to_bucket(0.0) == 0
    assert edc.entropy_to_bucket(10.0) == 7

def test_should_continue_drafting():
    """Test drafting decision."""
    edc = EDC()
    decision = edc.should_continue_drafting(5.0)
    assert isinstance(decision, bool)
```

## 📦 Pull Request Process

### 1. Ensure Quality

Before submitting:

```bash
# Format code
clang-format -i src/**/*.h src/**/*.cpp
black scripts/*.py

# Run lints
cpplint src/**/*.{h,cpp}
pylint scripts/*.py

# Run tests
pytest tests/

# Validate hardware costs still pass
python3 scripts/validate_hardware_costs.py
```

### 2. Commit Messages

Use conventional commits:

```
feat: add support for custom algorithms
fix: correct TVC timing calculation
docs: update installation guide
test: add EDC unit tests
refactor: simplify queue management
perf: optimize AAU throughput calculation
```

### 3. Create Pull Request

- Fill out the PR template completely
- Reference related issues (#123)
- Include screenshots/results if applicable
- Ensure CI passes

### 4. Code Review

- Address reviewer comments
- Keep discussion professional
- Update based on feedback
- Squash commits if requested

## 🐛 Reporting Bugs

### Before Reporting

1. Search existing issues
2. Try latest version
3. Check documentation
4. Verify it's not a configuration issue

### Bug Report Template

```markdown
**Description**
A clear description of the bug.

**To Reproduce**
Steps to reproduce:
1. Run command '...'
2. With configuration '...'
3. See error

**Expected Behavior**
What should happen.

**Actual Behavior**
What actually happens.

**Environment**
- OS: Ubuntu 22.04
- GCC version: 11.3
- Python version: 3.10
- AHASD commit: abc1234

**Logs**
```
Paste relevant logs here
```

**Additional Context**
Any other relevant information.
```

## ✨ Feature Requests

### Feature Request Template

```markdown
**Problem**
Describe the problem this feature would solve.

**Proposed Solution**
Describe your preferred solution.

**Alternatives Considered**
Other solutions you've considered.

**Additional Context**
Mockups, examples, related work, etc.
```

## 📚 Documentation Contributions

### Areas Needing Documentation

- Tutorials for specific use cases
- Translations to other languages
- Video guides
- API documentation
- Architecture deep-dives

### Documentation Style Guide

- Use Markdown
- Add code examples
- Include diagrams (draw.io or ASCII)
- Keep sections focused
- Cross-reference related docs

## 🏆 Recognition

Contributors are recognized in:
- README Contributors section
- Release notes
- Paper acknowledgments (for significant contributions)

## 📧 Contact

- **Questions**: Open a discussion on GitHub
- **Security Issues**: Email directly (see SECURITY.md)
- **General**: your.email@university.edu

## 📜 License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.

---

Thank you for contributing to AHASD! 🎉

