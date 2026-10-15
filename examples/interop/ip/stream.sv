package types;
    typedef struct packed {
        logic [7:0] data;
        logic valid;
    } packet_t;
endpackage

interface Stream #(parameter type T = types::packet_t);
    T data;
    modport source(output data);
    modport sink(input data);
endinterface

module array_reader #(parameter N = 2)
    (Stream.sink links[0:N-1], output types::packet_t y);
    assign y = links[0].data;
endmodule
