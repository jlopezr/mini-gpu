int use(int *p) { return p[0]+p[1]+p[2]+p[3]; }
int arrays(void) { int a[4]={1,2,3,4}; return use(a); }
int main(void) { return arrays(); }
