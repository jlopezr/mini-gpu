
volatile unsigned mmio;
int probe(void) { unsigned a=mmio; mmio=a+1; return mmio; }
int main(void) { mmio=4; return probe(); }
