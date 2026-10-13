#include <math.h>
#include <stdint.h>
void raster(int n, float *p, unsigned char *c, int w, int h, unsigned char *img, float *zbuf){
for(int k=0;k<n;k++){
float *v=p+9*k;float x0=v[0],y0=v[1],x1=v[3],y1=v[4],x2=v[6],y2=v[7];
float den=(y1-y2)*(x0-x2)+(x2-x1)*(y0-y2);if(fabsf(den)<1e-8f)continue;
int xmin=fmaxf(0,floorf(fminf(x0,fminf(x1,x2)))),xmax=fminf(w-1,ceilf(fmaxf(x0,fmaxf(x1,x2))));
int ymin=fmaxf(0,floorf(fminf(y0,fminf(y1,y2)))),ymax=fminf(h-1,ceilf(fmaxf(y0,fmaxf(y1,y2))));
for(int y=ymin;y<=ymax;y++)for(int x=xmin;x<=xmax;x++){
float a=((y1-y2)*(x+.5f-x2)+(x2-x1)*(y+.5f-y2))/den;
float b=((y2-y0)*(x+.5f-x2)+(x0-x2)*(y+.5f-y2))/den;float d=1-a-b;
if(a<0||b<0||d<0)continue;float z=a*v[2]+b*v[5]+d*v[8];int i=y*w+x;
if(z>zbuf[i]){zbuf[i]=z;img[3*i]=c[3*k];img[3*i+1]=c[3*k+1];img[3*i+2]=c[3*k+2];}
}
}
}
