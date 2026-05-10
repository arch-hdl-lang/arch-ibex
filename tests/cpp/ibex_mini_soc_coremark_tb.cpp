#include "Vibex_mini_soc.h"
#include "Vibex_mini_soc___024root.h"
#include "verilated.h"

#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>

namespace {

std::uint64_t max_cycles_from_env() {
  const char *raw = std::getenv("COREMARK_MAX_CYCLES");
  if (raw == nullptr || raw[0] == '\0') {
    return 20'000'000ULL;
  }
  return std::strtoull(raw, nullptr, 10);
}

void tick(VerilatedContext &contextp, Vibex_mini_soc &top) {
  top.IO_CLK = 0;
  top.eval();
  contextp.timeInc(5);

  top.IO_CLK = 1;
  top.eval();
  contextp.timeInc(5);
}

void load_vmem(Vibex_mini_soc &top) {
  const char *path = std::getenv("VMEM_PATH");
  if (path == nullptr || path[0] == '\0') {
    throw std::runtime_error("VMEM_PATH is required");
  }

  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error(std::string("failed to open VMEM_PATH: ") + path);
  }

  std::string line;
  std::uint32_t index = 0;
  while (std::getline(input, line)) {
    if (line.empty() || line.rfind("//", 0) == 0 || line.rfind("#", 0) == 0) {
      continue;
    }
    if (line[0] == '@') {
      std::ostringstream msg;
      msg << "unexpected @addr line in VMEM_PATH at word " << index;
      throw std::runtime_error(msg.str());
    }
    std::uint32_t word = 0;
    std::stringstream parser(line);
    parser >> std::hex >> word;
    if (parser.fail()) {
      throw std::runtime_error(std::string("failed to parse VMEM line: ") + line);
    }
    top.rootp->ibex_mini_soc__DOT__u_ram__DOT__u_ram__DOT__mem[index] = word;
    ++index;
  }
  std::cout << "ARCH_IBEX_LOADED_WORDS=" << index << "\n";
}

}  // namespace

int main(int argc, char **argv) {
  auto contextp = std::make_unique<VerilatedContext>();
  contextp->commandArgs(argc, argv);

  auto top = std::make_unique<Vibex_mini_soc>(contextp.get());
  top->ext_irq_sources_i = 0;
  load_vmem(*top);

  // Match the cocotb SoC tests: begin deasserted, assert reset for a few
  // cycles, then release and run until software asks simulator_ctrl to finish.
  top->IO_RST_N = 1;
  tick(*contextp, *top);
  top->IO_RST_N = 0;
  for (int i = 0; i < 6; ++i) {
    tick(*contextp, *top);
  }
  top->IO_RST_N = 1;

  const std::uint64_t max_cycles = max_cycles_from_env();
  std::uint64_t cycles = 0;
  while (!contextp->gotFinish() && cycles < max_cycles) {
    tick(*contextp, *top);
    ++cycles;
  }

  top->final();

  std::cout << "ARCH_IBEX_SIM_CYCLES=" << cycles << "\n";
  if (!contextp->gotFinish()) {
    std::cerr << "CoreMark simulation timed out after " << max_cycles
              << " cycles; pc=0x" << std::hex
              << static_cast<std::uint32_t>(top->ibex_pc_o) << std::dec
              << "\n";
    return 1;
  }
  return 0;
}
