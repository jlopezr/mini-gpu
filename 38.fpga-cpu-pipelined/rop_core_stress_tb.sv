`timescale 1ns/1ps
`default_nettype none

// Estres de rop_core con comandos aleatorios contra un modelo de referencia.
//
// rop_core_tb.sv prueba cada operacion con unas pocas geometrias fijas. Aqui
// cada comando se genera al azar (operacion, formatos de 16/32 bits, los siete
// modos de comparacion con y sin signo, mascaras de escritura, alineaciones de
// color y Z independientes, anchos, filas, dx/dy negativos y con
// desbordamiento) y se aplica tambien a `refm`, una copia de la memoria, con
// un modelo escrito desde la semantica de rop_core.v. Despues de cada comando
// las dos memorias tienen que coincidir byte a byte.
//
// La memoria contesta como en dma_engine_stress_tb: respuesta en el flanco de
// bajada, estable hasta el handshake, con contrapresion y latencia aleatorias
// y en orden. Los contadores del final obligan a que el estres haya ocurrido
// (los 8 tags llenos, peticiones frenadas, respuestas retrasadas, lecturas de
// Z con escrituras aun pendientes, grupos de 8 pixeles, mascaras parciales,
// pasa/no pasa de la prueba de Z y saturaciones por abajo y por arriba).
//
// Semilla: +seed=N (por defecto 1). Comandos: +n=N (por defecto 400).
// +late_writes: memoria que no ordena lecturas tras escrituras pendientes.
module rop_core_stress_tb;
  localparam integer RAM = 32768;
  localparam integer COLOR_BASE = 0, Z_BASE = 16384, REGION = 16384;
  localparam integer QMAX = 64;

  reg clk = 0; always #5 clk = ~clk;
  reg reset = 1;
  reg cmd_valid = 0;
  reg [2:0] cmd_op = 0;
  reg [15:0] cmd_mode = 0;
  reg [319:0] cmd_params = 0;
  reg [255:0] cmd_frag_colors = 0, cmd_frag_z = 0;
  wire cmd_ready, done_valid, done_error, busy;
  wire req_valid, req_write, rsp_ready;
  reg req_ready = 0;
  wire [31:0] req_addr;
  wire [127:0] req_wdata;
  wire [15:0] req_wmask;
  reg rsp_valid = 0;
  reg [127:0] rsp_rdata = 0;
  reg rsp_error = 0;

  rop_core #(.TAG_DEPTH(8)) dut (.*);

  reg [7:0] mem [0:RAM-1];
  reg [7:0] refm [0:RAM-1];

  integer seed = 1, seed0 = 1, ncmd = 400;
  function integer rnd(input integer n);
    rnd = ($random(seed) & 32'h7fffffff) % n;
  endfunction

  // ---- Memoria: cola en orden, respuestas en el flanco de bajada ----------
  reg [127:0] q_data [0:QMAX-1];
  // +late_writes: la escritura se aplica al llegar su respuesta, no al
  // aceptarla. Modela una memoria que no ordena una lectura respecto a una
  // escritura anterior aun pendiente. rop_core ya no tiene barrera entre
  // grupos (S_SP_SYNC): tiene que dar lo mismo, porque las escrituras llevan
  // mascara de bytes y dos grupos que comparten palabra tocan pixeles
  // distintos. La SDRAM de la 38 SI ordena (READ/WRITE en orden de llegada),
  // asi que por defecto las escrituras se aplican al aceptarlas.
  reg late_writes = 0;
  reg q_write [0:QMAX-1];
  reg [31:0] q_addr [0:QMAX-1];
  reg [127:0] q_wdata [0:QMAX-1];
  reg [15:0] q_wmask [0:QMAX-1];
  integer q_due [0:QMAX-1];
  integer q_head = 0, q_tail = 0, q_count = 0, tick = 0;
  reg consumed = 0;
  integer accepted = 0, completed = 0, peak = 0, stalled = 0, delayed = 0;
  integer partial_masks = 0, overlap_reads = 0, groups8 = 0;
  integer b;
  reg [127:0] temp;

  always @(negedge clk) begin
    if (reset) begin
      req_ready = 0; rsp_valid = 0; rsp_rdata = 0; rsp_error = 0;
    end else begin
      tick = tick + 1;
      req_ready = (rnd(4) != 0);
      if (!rsp_valid || consumed) begin
        rsp_valid = (q_count != 0) && (tick >= q_due[q_head]);
        rsp_rdata = (q_count != 0) ? q_data[q_head] : 128'd0;
        rsp_error = 1'b0;
      end
      consumed = 0;
    end
  end

  always @(posedge clk) begin
    if (!reset) begin
      if (req_valid && !req_ready) stalled = stalled + 1;
      if (q_count != 0 && !rsp_valid) delayed = delayed + 1;
      // Una lectura de Z con escrituras aun pendientes: ya no hay barrera.
      if (dut.state == 4'd8 && req_valid && req_ready && dut.tag_count != 0)
        overlap_reads = overlap_reads + 1;
      if (dut.state == 4'd14 && dut.sp_pixel_index == 0 && dut.sp_step == 8)
        groups8 = groups8 + 1;
      if (rsp_valid && rsp_ready) begin
        consumed = 1;
        if (q_count == 0) $fatal(1, "response with empty queue");
        if (late_writes && q_write[q_head])
          for (b = 0; b < 16; b = b + 1)
            if (q_wmask[q_head][b]) mem[q_addr[q_head]+b] = q_wdata[q_head][8*b +: 8];
        q_head = (q_head + 1) % QMAX;
        q_count = q_count - 1;
        completed = completed + 1;
      end
      if (req_valid && req_ready) begin
        if (req_addr[3:0] !== 4'd0 || req_addr > RAM - 16)
          $fatal(1, "unaligned or out-of-range request addr=%h", req_addr);
        if (q_count == QMAX) $fatal(1, "memory queue full");
        temp = 128'd0;
        for (b = 0; b < 16; b = b + 1) temp[8*b +: 8] = mem[req_addr+b];
        if (req_write) begin
          if (req_wmask != 16'hffff) partial_masks = partial_masks + 1;
          if (!late_writes)
            for (b = 0; b < 16; b = b + 1)
              if (req_wmask[b]) mem[req_addr+b] = req_wdata[8*b +: 8];
        end
        q_write[q_tail] = req_write;
        q_addr[q_tail] = req_addr;
        q_wdata[q_tail] = req_wdata;
        q_wmask[q_tail] = req_wmask;
        q_data[q_tail] = temp;
        // En orden: una respuesta nunca vence antes que la anterior.
        // A veces una respuesta lenta (hasta 40 ciclos): las escrituras
        // siguientes se acumulan hasta llenar los 8 tags (tags_full).
        q_due[q_tail] = tick + 1 + ((rnd(6) == 0) ? rnd(40) : rnd(9));
        if (q_count != 0 && q_due[q_tail] < q_due[(q_tail + QMAX - 1) % QMAX])
          q_due[q_tail] = q_due[(q_tail + QMAX - 1) % QMAX];
        q_tail = (q_tail + 1) % QMAX;
        q_count = q_count + 1;
        if (q_count > peak) peak = q_count;
        accepted = accepted + 1;
      end
    end
  end

  // ---- Modelo de referencia -------------------------------------------------
  function [31:0] rd(input integer a, input integer bytes);
    rd = (bytes == 4) ? {refm[a+3], refm[a+2], refm[a+1], refm[a]}
                      : {16'd0, refm[a+1], refm[a]};
  endfunction
  task wr(input integer a, input integer bytes, input [31:0] v);
    begin
      refm[a] = v[7:0]; refm[a+1] = v[15:8];
      if (bytes == 4) begin refm[a+2] = v[23:16]; refm[a+3] = v[31:24]; end
    end
  endtask

  integer passes = 0, fails = 0, sat_lo = 0, sat_hi = 0;

  // La Z que guarda y compara rop_core: acumulador >>> FRAC (mode[11:8]) y,
  // con Z16, los 16 bits bajos o, con SAT (mode[13]), saturada a 0..65535.
  function [31:0] zformat(input [15:0] mode, input [31:0] v);
    reg signed [31:0] sh;
    begin
      sh = $signed(v) >>> mode[11:8];
      if (mode[4]) zformat = sh;
      else if (!mode[13]) zformat = {16'd0, sh[15:0]};
      else if (sh < 0) zformat = 32'd0;
      else if (sh > 65535) zformat = 32'd65535;
      else zformat = {16'd0, sh[15:0]};
    end
  endfunction
  integer cmp_used [0:6];

  // La prueba de Z de rop_core: `nv` y `ov` ya recortados al ancho (16 o 32
  // bits); con signo, se compara como entero con signo de ese ancho.
  function pass_cmp(input [2:0] cmp, input sgn, input z32,
                    input [31:0] nv, input [31:0] ov);
    reg signed [32:0] sn, so;
    begin
      if (sgn) begin
        sn = z32 ? {nv[31], nv} : {{17{nv[15]}}, nv[15:0]};
        so = z32 ? {ov[31], ov} : {{17{ov[15]}}, ov[15:0]};
      end else begin
        sn = {1'b0, nv}; so = {1'b0, ov};
      end
      case (cmp)
        3'd0: pass_cmp = 1;
        3'd1: pass_cmp = (sn == so);
        3'd2: pass_cmp = (sn != so);
        3'd3: pass_cmp = (sn < so);
        3'd4: pass_cmp = (sn <= so);
        3'd5: pass_cmp = (sn > so);
        3'd6: pass_cmp = (sn >= so);
        default: pass_cmp = 0;
      endcase
    end
  endfunction

  // Un pixel de SPAN o FRAGMENT. `mode` es el modo efectivo: [2:0] cmp,
  // [3] color32, [4] z32, [5] escribe Z, [6] escribe color, [7] con signo.
  task model_pixel(input [15:0] mode, input integer ca, input integer za,
                   input [31:0] v, input [31:0] color, input covered);
    reg [31:0] nv, ov;
    reg p;
    integer zb, cb;
    begin
      zb = mode[4] ? 4 : 2;
      cb = mode[3] ? 4 : 2;
      nv = zformat(mode, v);
      if (!mode[4] && mode[13]) begin
        if ($signed(v) >>> mode[11:8] < 0) sat_lo = sat_lo + 1;
        else if (($signed(v) >>> mode[11:8]) > 65535) sat_hi = sat_hi + 1;
      end
      ov = rd(za, zb);
      p = covered && pass_cmp(mode[2:0], mode[7], mode[4], nv, ov);
      if (mode[2:0] != 0) begin if (p) passes = passes + 1; else fails = fails + 1; end
      if (p) begin
        if (mode[5]) wr(za, zb, nv);
        if (mode[6]) wr(ca, cb, mode[3] ? color : {16'd0, color[15:0]});
      end
    end
  endtask

  task model_span(input [15:0] mode, input integer cbase, input integer zbase,
                  input integer w, input integer h, input integer cs, input integer zs,
                  input [31:0] color, input [31:0] z0, input [31:0] dx, input [31:0] dy);
    integer x, y;
    reg [31:0] rowz;
    begin
      rowz = z0;
      for (y = 0; y < h; y = y + 1) begin
        for (x = 0; x < w; x = x + 1)
          model_pixel(mode, cbase + y*cs + x*(mode[3] ? 4 : 2),
                      zbase + y*zs + x*(mode[4] ? 4 : 2),
                      rowz + x*dx, color, 1'b1);
        rowz = rowz + dy;
      end
    end
  endtask

  task model_fragment(input [15:0] mode, input integer cbase, input integer zbase,
                      input integer n, input [7:0] cov,
                      input [255:0] colors, input [255:0] zs);
    integer q;
    begin
      for (q = 0; q < n; q = q + 1)
        model_pixel(mode, cbase + q*(mode[3] ? 4 : 2), zbase + q*(mode[4] ? 4 : 2),
                    zs[32*q +: 32], colors[32*q +: 32], cov[q]);
    end
  endtask

  // GENERATE2D: [2:0] cmp, [3] 32 bits, [4] con signo. Ancho en pixeles.
  task model_gen(input [12:0] mode, input integer dst, input integer w, input integer h,
                 input integer stride, input [31:0] z0, input [31:0] dx, input [31:0] dy);
    integer x, y, bytes;
    reg [31:0] v, nv, ov;
    begin
      bytes = mode[3] ? 4 : 2;
      for (y = 0; y < h; y = y + 1)
        for (x = 0; x < w; x = x + 1) begin
          v = z0 + y*dy + x*dx;
          nv = mode[3] ? v : {16'd0, v[15:0]};
          ov = rd(dst + y*stride + x*bytes, bytes);
          if (pass_cmp(mode[2:0], mode[4], mode[3], nv, ov))
            wr(dst + y*stride + x*bytes, bytes, nv);
        end
    end
  endtask

  // ---- Ejecutar un comando y comprobar ------------------------------------
  integer cmd_index = 0, i;
  task automatic issue(input [2:0] op, input [15:0] mode, input [319:0] params);
    integer watch;
    begin
      // Sin hueco: el comando sale en cuanto cmd_ready esta alto.
      while (!cmd_ready) @(negedge clk);
      cmd_op = op; cmd_mode = mode; cmd_params = params; cmd_valid = 1;
      @(negedge clk); cmd_valid = 0;
      watch = 0;
      while (!done_valid) begin
        @(negedge clk); watch = watch + 1;
        if (watch > 200000) $fatal(1, "timeout, command %0d op %0d", cmd_index, op);
      end
      if (done_error) $fatal(1, "seed %0d command %0d op %0d mode %h reported error", seed0, cmd_index, op, mode);
      for (i = 0; i < RAM; i = i + 1)
        if (mem[i] !== refm[i])
          $fatal(1, "seed %0d command %0d op %0d mode %h: byte %h is %h, model %h",
                 seed0, cmd_index, op, mode, i, mem[i], refm[i]);
      cmd_index = cmd_index + 1;
    end
  endtask

  // Direccion aleatoria dentro de una region, alineada a `align`, con sitio
  // para `extent` bytes.
  function integer place(input integer base, input integer extent, input integer align);
    place = base + ((rnd(REGION - extent - 32) / align) * align);
  endfunction

  // Valores de 32 bits con extremos: pequenos, negativos, cerca del limite.
  function [31:0] rval;
    integer k;
    begin
      k = rnd(6);
      case (k)
        5: rval = (32'd65535 << rnd(16)) - 32 + rnd(64);
        0: rval = rnd(64);
        1: rval = -rnd(64);
        2: rval = 32'h7fff_fff0 + rnd(32);
        3: rval = 32'h0000_7ff0 + rnd(32);
        default: rval = $random(seed);
      endcase
    end
  endfunction

  // Configuracion persistente, la misma que lleva rop_core.
  reg [31:0] c_color_base, c_z_base, c_color_stride, c_z_stride;
  reg [31:0] c_color, c_z0, c_dx, c_dy;
  reg [15:0] c_mode;
  reg configured = 0;

  // Modo aleatorio valido: cmp != 7, al menos una escritura, FRAC al azar
  // (0 la mitad de las veces) y SAT solo con Z16 sin signo. El bit 12
  // (compacto) y [15:14] a cero: vale como cmd_mode explicito y como modo
  // de render de CONFIG.
  function [15:0] rmode;
    reg [15:0] m;
    begin
      m = 0;
      m[7:0] = $random(seed);
      m[2:0] = rnd(7);
      if (!m[5] && !m[6]) m[5 + rnd(2)] = 1'b1;
      m[11:8] = rnd(2) ? rnd(16) : 0;
      m[13] = (!m[4] && !m[7]) ? rnd(2) : 1'b0;
      rmode = m;
    end
  endfunction

  integer op_count [0:6];
  integer k, w, h, cs, zs, cb, zb, n, nbytes, x;
  integer cbase, zbase, dst, src, stride;
  reg [15:0] m8;
  reg [7:0] cov;
  reg [12:0] m13;
  reg [31:0] color, z0, dx, dy, pat;
  reg [255:0] fc, fz;

  // Para que EQ/NE no fallen siempre: copia en la Z vieja el valor que traera
  // el span en algunos pixeles.
  task seed_equal_span(input [15:0] mode, input integer zbase, input integer w,
                       input integer h, input integer zs, input [31:0] z0,
                       input [31:0] dx, input [31:0] dy);
    integer x, y, a, bytes;
    reg [31:0] v;
    begin
      bytes = mode[4] ? 4 : 2;
      for (y = 0; y < h; y = y + 1)
        for (x = 0; x < w; x = x + 1)
          if (rnd(2)) begin
            v = zformat(mode, z0 + y*dy + x*dx);
            a = zbase + y*zs + x*bytes;
            mem[a] = v[7:0]; mem[a+1] = v[15:8];
            refm[a] = v[7:0]; refm[a+1] = v[15:8];
            if (bytes == 4) begin
              mem[a+2] = v[23:16]; mem[a+3] = v[31:24];
              refm[a+2] = v[23:16]; refm[a+3] = v[31:24];
            end
          end
    end
  endtask

  task random_span(input compact);
    begin
      m8 = compact ? c_mode : rmode();
      cb = m8[3] ? 4 : 2; zb = m8[4] ? 4 : 2;
      w = 1 + rnd(40); h = 1 + rnd(4);
      if (compact) begin
        cs = c_color_stride; zs = c_z_stride;
        // Los strides los fija CONFIG: el ancho se recorta para que una fila
        // no pise la siguiente.
        if (w*cb > cs) w = cs / cb;
        if (w*zb > zs) w = zs / zb;
      end else begin
        cs = w*cb + cb*rnd(8); zs = w*zb + zb*rnd(8);
      end
      cbase = place(COLOR_BASE, h*cs + 64, cb);
      zbase = place(Z_BASE, h*zs + 64, zb);
      color = $random(seed); z0 = rval(); dx = rval(); dy = rval();
      if (rnd(3) == 0) dx = rnd(4);
      if (!compact && (m8[2:0] == 1 || m8[2:0] == 2) && rnd(2))
        seed_equal_span(m8, zbase, w, h, zs, z0, dx, dy);
      if (compact) begin
        // Offsets respecto a las bases de CONFIG, y overrides al azar.
        m13 = 13'h1000;
        if (rnd(2)) m13[8] = 1; else color = c_color;
        if (rnd(2)) m13[9] = 1; else z0 = c_z0;
        if (rnd(2)) m13[10] = 1; else dx = c_dx;
        if (rnd(2)) m13[11] = 1; else dy = c_dy;
        if ((m8[2:0] == 1 || m8[2:0] == 2) && rnd(2))
          seed_equal_span(m8, zbase, w, h, zs, z0, dx, dy);
        model_span(m8, cbase, zbase, w, h, cs, zs, color, z0, dx, dy);
        issue(3'd3, m13, {64'd0, dy, dx, z0, color, h, w,
                          zbase - c_z_base, cbase - c_color_base});
        op_count[5] = op_count[5] + 1;
      end else begin
        model_span(m8, cbase, zbase, w, h, cs, zs, color, z0, dx, dy);
        issue(3'd3, m8, {dy, dx, z0, color, zs, cs, h, w, zbase, cbase});
        op_count[0] = op_count[0] + 1;
      end
      cmp_used[m8[2:0]] = cmp_used[m8[2:0]] + 1;
    end
  endtask

  task random_fragment(input compact);
    begin
      m8 = compact ? c_mode : rmode();
      cb = m8[3] ? 4 : 2; zb = m8[4] ? 4 : 2;
      n = 1 + rnd(8);
      cov = $random(seed);
      cov = cov & ((9'd1 << n) - 1);
      cbase = place(COLOR_BASE, 64, cb);
      zbase = place(Z_BASE, 64, zb);
      for (k = 0; k < 8; k = k + 1) begin
        fc[32*k +: 32] = $random(seed);
        fz[32*k +: 32] = rval();
        // Algunos carriles con la Z que ya hay, para EQ/NE.
        if (k < n && rnd(3) == 0)
          fz[32*k +: 32] = rd(zbase + k*zb, zb) << m8[11:8];
      end
      cmd_frag_colors = fc; cmd_frag_z = fz;
      model_fragment(m8, cbase, zbase, n, cov, fc, fz);
      if (compact) begin
        issue(3'd4, 13'h1000, {192'd0, {24'd0, cov}, n, zbase - c_z_base, cbase - c_color_base});
        op_count[6] = op_count[6] + 1;
      end else begin
        issue(3'd4, m8, {192'd0, {24'd0, cov}, n, zbase, cbase});
        op_count[1] = op_count[1] + 1;
      end
      cmp_used[m8[2:0]] = cmp_used[m8[2:0]] + 1;
    end
  endtask

  task random_gen;
    begin
      m13 = 0;
      m13[2:0] = rnd(7);
      m13[3] = rnd(2);
      m13[4] = rnd(2);
      nbytes = m13[3] ? 4 : 2;
      w = (m13[3] ? 4 : 8) * (1 + rnd(4));
      h = 1 + rnd(3);
      stride = 16 * ((w*nbytes + 15) / 16 + rnd(3));
      dst = place(Z_BASE, h*stride + 64, 16);
      z0 = rval(); dx = rval(); dy = rval();
      if (rnd(3) == 0) dx = rnd(4);
      model_gen(m13, dst, w, h, stride, z0, dx, dy);
      issue(3'd2, m13, {96'd0, dy, dx, z0, stride, h, w, dst});
      op_count[2] = op_count[2] + 1;
      cmp_used[m13[2:0]] = cmp_used[m13[2:0]] + 1;
    end
  endtask

  task random_fill_copy;
    begin
      w = 16 * (1 + rnd(6)); h = 1 + rnd(3);
      stride = w + 16 * rnd(3);
      if (rnd(2)) begin
        dst = place(COLOR_BASE, h*stride + 64, 16);
        pat = $random(seed);
        for (k = 0; k < h; k = k + 1)
          for (x = 0; x < w; x = x + 4) wr(dst + k*stride + x, 4, pat);
        issue(3'd0, 13'd0, {160'd0, pat, stride, h, w, dst});
        op_count[3] = op_count[3] + 1;
      end else begin
        src = place(COLOR_BASE, h*stride + 64, 16);
        dst = place(Z_BASE, h*stride + 64, 16);
        for (k = 0; k < h; k = k + 1)
          for (x = 0; x < w; x = x + 1) refm[dst + k*stride + x] = refm[src + k*stride + x];
        issue(3'd1, 13'd0, {128'd0, stride, stride, h, w, dst, src});
        op_count[4] = op_count[4] + 1;
      end
    end
  endtask

  task random_config;
    reg [4:0] sel;
    begin
      sel = configured ? (1 + rnd(31)) : 5'b11111;
      if (sel[0]) begin
        c_color_base = COLOR_BASE + 4 * rnd(64);
        c_z_base = Z_BASE + 4 * rnd(64);
      end
      if (sel[1]) begin
        c_color_stride = 4 * (20 + rnd(20));
        c_z_stride = 4 * (20 + rnd(20));
      end
      if (sel[2]) c_color = $random(seed);
      if (sel[3]) begin c_z0 = rval(); c_dx = rval(); c_dy = rval(); end
      if (sel[4]) c_mode = rmode();
      issue(3'd5, {11'd0, sel}, {32'd0, {16'd0, c_mode}, c_dy, c_dx, c_z0, c_color,
                                c_z_stride, c_color_stride, c_z_base, c_color_base});
      configured = 1;
    end
  endtask

  initial begin
    if (!$value$plusargs("seed=%d", seed)) seed = 1;
    seed0 = seed;   // `seed` cambia con cada $random; para reproducir, la inicial
    if (!$value$plusargs("n=%d", ncmd)) ncmd = 400;
    late_writes = $test$plusargs("late_writes");
    $display("rop_core_stress_tb: seed=%0d commands=%0d late_writes=%0d", seed, ncmd, late_writes);
    for (i = 0; i < RAM; i = i + 1) begin
      mem[i] = $random(seed);
      refm[i] = mem[i];
    end
    for (i = 0; i < 7; i = i + 1) begin cmp_used[i] = 0; op_count[i] = 0; end
    repeat (4) @(negedge clk);
    reset = 0;
    @(negedge clk);
    while (cmd_index < ncmd) begin
      k = rnd(100);
      if (k < 35) random_span(1'b0);
      else if (k < 55) random_fragment(1'b0);
      else if (k < 67) random_gen;
      else if (k < 75) random_fill_copy;
      else if (k < 80 || !configured) random_config;
      else if (k < 92) random_span(1'b1);
      else random_fragment(1'b1);
    end
    // Cobertura: que el estres haya ocurrido de verdad.
    if (accepted != completed || q_count != 0)
      $fatal(1, "pending responses: accepted=%0d completed=%0d", accepted, completed);
    if (peak < 8 || stalled == 0 || delayed == 0 || overlap_reads == 0 || groups8 == 0 ||
        partial_masks == 0 || passes == 0 || fails == 0 || sat_lo == 0 || sat_hi == 0)
      $fatal(1, "insufficient coverage: peak=%0d stalled=%0d delayed=%0d overlap=%0d groups8=%0d partial=%0d pass=%0d fail=%0d satlo=%0d sathi=%0d",
             peak, stalled, delayed, overlap_reads, groups8, partial_masks, passes, fails, sat_lo, sat_hi);
    for (i = 0; i < 7; i = i + 1)
      if (cmp_used[i] == 0) $fatal(1, "comparison mode %0d never used", i);
    $display("PASS rop_core_stress_tb seed=%0d commands=%0d requests=%0d peak=%0d stalled=%0d delayed=%0d overlap=%0d groups8=%0d partial=%0d zpass=%0d zfail=%0d satlo=%0d sathi=%0d",
             seed0, cmd_index, accepted, peak, stalled, delayed, overlap_reads, groups8, partial_masks, passes, fails, sat_lo, sat_hi);
    $display("  span=%0d frag=%0d gen=%0d fill=%0d copy=%0d compact_span=%0d compact_frag=%0d",
             op_count[0], op_count[1], op_count[2], op_count[3], op_count[4], op_count[5], op_count[6]);
    $finish;
  end
endmodule

`default_nettype wire
