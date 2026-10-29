#include "minifont.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char **argv){
 assert(argc==2);FILE *f=fopen(argv[1],"rb");assert(f);
 assert(fseek(f,0,SEEK_END)==0);long n=ftell(f);assert(n>32);rewind(f);
 unsigned char *p=malloc((size_t)n);assert(p);assert(fread(p,1,(size_t)n,f)==(size_t)n);fclose(f);
 MfFont mf;assert(mf_open(&mf,p,(size_t)n)==0);
 assert(mf.font_spacing==2);
 p[6]=0;p[7]=0;p[28]=0;p[29]=0;
 assert(mf_open(&mf,p,(size_t)n)==0);assert(mf.font_spacing==0);
 p[28]=2;assert(mf_open(&mf,p,(size_t)n)!=0);
 free(p);puts("Spacing compatibility tests passed");return 0;
}
