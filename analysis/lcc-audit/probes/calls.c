int inc(int x) { return x + 1; }
int mix(int a, int b) { int x = inc(a); int y = inc(b); return x + y + inc(a+b); }
int main(void) { return mix(3, 4); }
