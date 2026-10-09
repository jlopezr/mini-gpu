int control(int n) { int s=0,i; for(i=0;i<n;i++) if(i&1) s+=i; else s-=i; return s; }
int main(void) { return control(10); }
