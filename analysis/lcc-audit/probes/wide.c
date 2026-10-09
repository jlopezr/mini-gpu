unsigned long long wide(unsigned a,unsigned b){return ((unsigned long long)a*b)+0x100000002ULL;}
int main(void) { return (int)wide(7,9); }
