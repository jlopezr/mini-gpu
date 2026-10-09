
int constprop(int x) { int a=7; return a+x; }
int copyprop(int x) { int a=x; int b=a; return b+1; }
int deadstore(int x) { int a=x+1; a=x+2; return x; }
int cse(int a,int b) { return (a+b)*(a+b); }
int unreachable(int x) { if(x) return 1; else return 2; return 99; }
int invariant(int *p,int n) { int i,s=0; for(i=0;i<n;i++) s += p[0]+3; return s; }
int tail(int x) { return constprop(x); }
int main(void) { int v=3; return constprop(v)+copyprop(v)+deadstore(v)+cse(v,2)+unreachable(v)+invariant(&v,2)+tail(v); }
