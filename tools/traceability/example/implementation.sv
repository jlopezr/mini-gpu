// @artifact IMPL-DEVICE-IDENTITY type=implementation
// @implements SPEC-DEVICE@identity
// @satisfies REQ-DEVICE-IDENTITY
module device_identity (
    input  wire [31:0] address,
    output wire [31:0] read_data
);
    assign read_data = address[2] ? 32'h4D475001 : 32'h00000000;
endmodule

// identity-read @implements SPEC-DEVICE#identity-register
module identity_read_path;
endmodule
