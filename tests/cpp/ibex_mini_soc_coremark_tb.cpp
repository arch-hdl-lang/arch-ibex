#include "Vibex_mini_soc.h"
#include "Vibex_mini_soc___024root.h"
#include "verilated.h"
#include "verilated_vcd_c.h"

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

std::uint64_t env_u64(const char *name, std::uint64_t default_value) {
  const char *raw = std::getenv(name);
  if (raw == nullptr || raw[0] == '\0') {
    return default_value;
  }
  return std::strtoull(raw, nullptr, 10);
}

bool env_is_set(const char *name) {
  const char *raw = std::getenv(name);
  return raw != nullptr && raw[0] != '\0';
}

bool core_icache_enabled(const Vibex_mini_soc &top) {
  return top.rootp
             ->ibex_mini_soc__DOT__u_ibex__DOT__u_ibex_top__DOT__u_ibex_core__DOT__icache_enable !=
         0;
}

class TraceWindow {
 public:
  explicit TraceWindow(VerilatedContext &contextp) {
    const char *path = std::getenv("COREMARK_VCD");
    if (path == nullptr || path[0] == '\0') {
      return;
    }

    enabled_ = true;
    path_ = path;
    after_cycles_ = env_u64("COREMARK_VCD_AFTER_CYCLES", 2000);
    start_cycle_ = env_u64("COREMARK_VCD_START_CYCLE", 0);
    start_by_cycle_ = env_is_set("COREMARK_VCD_START_CYCLE");
    contextp.traceEverOn(true);
  }

  void attach(Vibex_mini_soc &top) {
    if (!enabled_) {
      return;
    }

    trace_ = std::make_unique<VerilatedVcdC>();
    top.trace(trace_.get(), 99);
    trace_->open(path_.c_str());
  }

  void maybe_start(std::uint64_t cycle, const Vibex_mini_soc &top,
                   const VerilatedContext &contextp) {
    if (!enabled_ || dumping_ || done_) {
      return;
    }

    const bool start_now =
        start_by_cycle_ ? (cycle >= start_cycle_) : core_icache_enabled(top);
    if (!start_now) {
      return;
    }

    dumping_ = true;
    stop_cycle_ = cycle + after_cycles_;
    std::cout << "ARCH_IBEX_VCD_START cycle=" << cycle
              << " path=" << path_
              << " stop_cycle=" << stop_cycle_
              << " trigger=" << (start_by_cycle_ ? "cycle" : "icache_enable")
              << "\n";
    dump(contextp);
  }

  void maybe_stop(std::uint64_t cycle) {
    if (!dumping_ || cycle <= stop_cycle_) {
      return;
    }
    close();
    std::cout << "ARCH_IBEX_VCD_STOP cycle=" << cycle << "\n";
  }

  void dump(const VerilatedContext &contextp) {
    if (dumping_ && trace_) {
      trace_->dump(contextp.time());
    }
  }

  void close() {
    if (trace_) {
      trace_->flush();
      trace_->close();
    }
    dumping_ = false;
    done_ = true;
  }

 private:
  bool enabled_ = false;
  bool dumping_ = false;
  bool done_ = false;
  bool start_by_cycle_ = false;
  std::uint64_t start_cycle_ = 0;
  std::uint64_t stop_cycle_ = 0;
  std::uint64_t after_cycles_ = 0;
  std::string path_;
  std::unique_ptr<VerilatedVcdC> trace_;
};

void tick(VerilatedContext &contextp, Vibex_mini_soc &top, TraceWindow &trace) {
  top.IO_CLK = 0;
  top.eval();
  trace.dump(contextp);
  contextp.timeInc(5);

  top.IO_CLK = 1;
  top.eval();
  trace.dump(contextp);
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
  TraceWindow trace(*contextp);

  auto top = std::make_unique<Vibex_mini_soc>(contextp.get());
  trace.attach(*top);
  top->ext_irq_sources_i = 0;
  load_vmem(*top);

  // Match the cocotb SoC tests: begin deasserted, assert reset for a few
  // cycles, then release and run until software asks simulator_ctrl to finish.
  top->IO_RST_N = 1;
  tick(*contextp, *top, trace);
  top->IO_RST_N = 0;
  for (int i = 0; i < 6; ++i) {
    tick(*contextp, *top, trace);
  }
  top->IO_RST_N = 1;

  const std::uint64_t max_cycles = env_u64("COREMARK_MAX_CYCLES", 20'000'000ULL);
  std::uint64_t cycles = 0;
  while (!contextp->gotFinish() && cycles < max_cycles) {
    tick(*contextp, *top, trace);
    ++cycles;
    trace.maybe_start(cycles, *top, *contextp);
    trace.maybe_stop(cycles);
  }

  top->final();
  trace.close();

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
