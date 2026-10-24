// Tag/data RAM model for the icache miter (prim_ram_1p-like: 1-cycle read,
// read data held between reads). Coherent without arrays: initial contents
// are a fixed but arbitrary function of (way, index) (anyconst seeds);
// writes go to a per-way log of the last NT/ND writes, read newest-first.
// Traces are restricted (assume) to at most NT tag / ND data writes per way,
// so the log never overflows.
module ram_model #(parameter NT = 10, parameter ND = 6) (
  input clk,
  input [1:0] tag_req, input tag_write, input [7:0] tag_addr, input [21:0] tag_wdata,
  input [1:0] data_req, input data_write, input [7:0] data_addr, input [63:0] data_wdata,
  output [43:0] tag_rdata, output [127:0] data_rdata
);
  (* anyconst *) reg [21:0] f_tseed0, f_tseed1;
  (* anyconst *) reg [7:0]  f_vseed0, f_vseed1;
  (* anyconst *) reg [63:0] f_dseed0, f_dseed1;
  reg [7:0]  tl_idx0 [0:NT-1]; reg [21:0] tl_val0 [0:NT-1]; reg [NT-1:0] tl_v0 = 0;
  reg [7:0]  tl_idx1 [0:NT-1]; reg [21:0] tl_val1 [0:NT-1]; reg [NT-1:0] tl_v1 = 0;
  reg [7:0]  dl_idx0 [0:ND-1]; reg [63:0] dl_val0 [0:ND-1]; reg [ND-1:0] dl_v0 = 0;
  reg [7:0]  dl_idx1 [0:ND-1]; reg [63:0] dl_val1 [0:ND-1]; reg [ND-1:0] dl_v1 = 0;
  reg [21:0] tq0 = 0, tq1 = 0; reg [63:0] dq0 = 0, dq1 = 0;
  reg [21:0] tr0, tr1; reg [63:0] dr0, dr1;
  integer k;
  always @(*) begin
    tr0 = {f_vseed0[tag_addr[2:0]], f_tseed0[20:8], f_tseed0[7:0] ^ tag_addr};
    tr1 = {f_vseed1[tag_addr[2:0]], f_tseed1[20:8], f_tseed1[7:0] ^ tag_addr};
    dr0 = f_dseed0 ^ {8{data_addr}};
    dr1 = f_dseed1 ^ {8{data_addr}};
    for (k = NT-1; k >= 0; k = k - 1) begin
      if (tl_v0[k] && tl_idx0[k] == tag_addr) tr0 = tl_val0[k];
      if (tl_v1[k] && tl_idx1[k] == tag_addr) tr1 = tl_val1[k];
    end
    for (k = ND-1; k >= 0; k = k - 1) begin
      if (dl_v0[k] && dl_idx0[k] == data_addr) dr0 = dl_val0[k];
      if (dl_v1[k] && dl_idx1[k] == data_addr) dr1 = dl_val1[k];
    end
  end
  wire tw0 = tag_req[0] && tag_write,   tw1 = tag_req[1] && tag_write;
  wire dw0 = data_req[0] && data_write, dw1 = data_req[1] && data_write;
  always @(*) begin
    if (tl_v0[NT-1]) assume (!tw0);
    if (tl_v1[NT-1]) assume (!tw1);
    if (dl_v0[ND-1]) assume (!dw0);
    if (dl_v1[ND-1]) assume (!dw1);
  end
  always @(posedge clk) begin
    if (tag_req[0] && !tag_write)   tq0 <= tr0;
    if (tag_req[1] && !tag_write)   tq1 <= tr1;
    if (data_req[0] && !data_write) dq0 <= dr0;
    if (data_req[1] && !data_write) dq1 <= dr1;
    if (tw0) begin
      for (k = NT-1; k > 0; k = k - 1) begin tl_idx0[k] <= tl_idx0[k-1]; tl_val0[k] <= tl_val0[k-1]; end
      tl_idx0[0] <= tag_addr; tl_val0[0] <= tag_wdata; tl_v0 <= {tl_v0[NT-2:0], 1'b1};
    end
    if (tw1) begin
      for (k = NT-1; k > 0; k = k - 1) begin tl_idx1[k] <= tl_idx1[k-1]; tl_val1[k] <= tl_val1[k-1]; end
      tl_idx1[0] <= tag_addr; tl_val1[0] <= tag_wdata; tl_v1 <= {tl_v1[NT-2:0], 1'b1};
    end
    if (dw0) begin
      for (k = ND-1; k > 0; k = k - 1) begin dl_idx0[k] <= dl_idx0[k-1]; dl_val0[k] <= dl_val0[k-1]; end
      dl_idx0[0] <= data_addr; dl_val0[0] <= data_wdata; dl_v0 <= {dl_v0[ND-2:0], 1'b1};
    end
    if (dw1) begin
      for (k = ND-1; k > 0; k = k - 1) begin dl_idx1[k] <= dl_idx1[k-1]; dl_val1[k] <= dl_val1[k-1]; end
      dl_idx1[0] <= data_addr; dl_val1[0] <= data_wdata; dl_v1 <= {dl_v1[ND-2:0], 1'b1};
    end
  end
  assign tag_rdata  = {tq0, tq1};
  assign data_rdata = {dq0, dq1};
endmodule
