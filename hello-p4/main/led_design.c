#include "led_design.h"
#include <math.h>
#include <string.h>

#define PI_F 3.14159265358979323846f
static const led_rgb_t rain_colors[15] = {
    {255,220,50},{240,50,255},{50,255,80},{50,240,255},{255,60,180},
    {40,120,255},{255,255,100},{40,255,180},{255,100,40},{100,40,255},
    {240,255,40},{30,180,255},{255,150,200},{30,255,30},{255,180,30}
};
static const led_rgb_t spark_colors[7] = {
    {0,0,255},{0,125,255},{0,255,255},{0,255,0},
    {255,0,0},{255,0,80},{255,0,210}
};
uint16_t led_design_index(unsigned row, unsigned col) {
    if (row >= LED_DESIGN_ROWS || col >= LED_DESIGN_COLS) return UINT16_MAX;
    return row*LED_DESIGN_COLS + ((row&1) ? LED_DESIGN_COLS-1-col : col);
}
static uint8_t wave(unsigned phase) {
    return (uint8_t)((sinf((uint8_t)phase * (2.0f*PI_F/256.0f))+1.0f)*127.5f);
}
static uint32_t random_next(led_design_t *d) {
    uint32_t x=d->random_state;
    x^=x<<13; x^=x>>17; x^=x<<5;
    return d->random_state=x;
}
static void clear(led_design_t *d) { memset(d->pixels,0,sizeof(d->pixels)); }
static void pixel(led_design_t *d,unsigned side,unsigned row,unsigned col,led_rgb_t color) {
    uint16_t i=led_design_index(row,col);
    if (side<2 && i!=UINT16_MAX) d->pixels[side][i]=color;
}
static void both(led_design_t *d,unsigned row,unsigned col,led_rgb_t color) {
    pixel(d,0,row,col,color); pixel(d,1,row,col,color);
}
static led_rgb_t scaled(led_rgb_t c,float amount) {
    return (led_rgb_t){(uint8_t)(c.r*amount),(uint8_t)(c.g*amount),(uint8_t)(c.b*amount)};
}
/* The old HSV helper produced B,G,R and passed those channels to an RGB API.
 * Preserve that visible palette explicitly; never change the driver's GRB format. */
static led_rgb_t palette(uint8_t hue,uint8_t sat,uint8_t value) {
    unsigned region=hue/43, rem=(hue-region*43)*6;
    uint8_t p=(value*(255-sat))>>8;
    uint8_t q=(value*(255-((sat*rem)>>8)))>>8;
    uint8_t t=(value*(255-((sat*(255-rem))>>8)))>>8;
    switch(region) {
        case 0:return (led_rgb_t){p,t,value};
        case 1:return (led_rgb_t){p,value,q};
        case 2:return (led_rgb_t){t,value,p};
        case 3:return (led_rgb_t){value,q,p};
        case 4:return (led_rgb_t){value,p,t};
        default:return (led_rgb_t){q,p,value};
    }
}
void led_design_init(led_design_t *d,uint32_t seed) {
    memset(d,0,sizeof(*d)); d->random_state=seed?seed:1; d->peak=2.0f;
}
static unsigned basic_period(unsigned pattern) {
    static const unsigned periods[6]={80,20,10,30,60,250};
    return periods[pattern];
}
static void basic(led_design_t *d,unsigned pattern) {
    unsigned f=d->frame;
    if(pattern!=1 && pattern!=4) clear(d);
    if(pattern==0) {
        unsigned row=(f/2)%6; if(row>=4)row=6-row;
        for(unsigned c=0;c<31;c++)both(d,row,c,(led_rgb_t){255,255,0});
    } else if(pattern==1) {
        for(unsigned r=0;r<4;r++)for(unsigned c=0;c<31;c++) {
            uint8_t v=wave(c*12+r*40+f*4);
            pixel(d,0,r,c,(led_rgb_t){v,0,v/4}); pixel(d,1,r,c,(led_rgb_t){v,v/4,0});
        }
    } else if(pattern==2) {
        for(unsigned n=0;n<20;n++) {
            unsigned i=(f%124+124-n)%124; uint8_t v=(20-n)*255/20;
            d->pixels[0][i]=(led_rgb_t){0,v,v/2}; d->pixels[1][i]=(led_rgb_t){0,v/2,v};
        }
    } else if(pattern==3) {
        unsigned step=f%16; uint8_t v=step<15?150-step*10:0;
        for(unsigned r=0;r<4;r++)for(unsigned side=0;side<2;side++) {
            led_rgb_t color=side?(led_rgb_t){0,v,255}:(led_rgb_t){0,255,v};
            pixel(d,side,r,15-step,color);pixel(d,side,r,15+step,color);
        }
    } else if(pattern==4) {
        for(unsigned side=0;side<2;side++) {
            for(unsigned i=0;i<124;i++) {
                led_rgb_t *p=&d->pixels[side][i];p->r=p->r*70/100;p->g=p->g*70/100;p->b=p->b*70/100;
            }
            for(unsigned r=0;r<3;r++)for(unsigned c=0;c<31;c++) {
                led_rgb_t above=d->pixels[side][led_design_index(r+1,c)];
                if(above.r|above.g|above.b)pixel(d,side,r,c,above);
            }
        }
        for(unsigned i=0;i<8;i++)if((f+i)%7==0)both(d,3,1+4*i,(led_rgb_t){255,255,0});
    } else {
        bool phase=(f%2)==0;
        for(unsigned r=0;r<4;r++)for(unsigned c=0;c<31;c++) {
            bool even=(r%2)==0;
            pixel(d,0,r,c,even?(phase?(led_rgb_t){255,180,0}:(led_rgb_t){0,0,200}):(phase?(led_rgb_t){0,255,200}:(led_rgb_t){255,180,0}));
            pixel(d,1,r,c,even?(phase?(led_rgb_t){255,0,180}:(led_rgb_t){0,200,255}):(phase?(led_rgb_t){0,200,255}:(led_rgb_t){255,0,180}));
        }
    }
}
static void rain(led_design_t *d) {
    for(unsigned i=0;i<124;i++) {
        led_rgb_t p=d->pixels[0][i];p.r=p.r*40/100;p.g=p.g*40/100;p.b=p.b*40/100;
        d->pixels[0][i]=d->pixels[1][i]=p;
    }
    unsigned step=d->frame%8;
    if(step<4)for(unsigned c=0;c<15;c++)both(d,3-step,1+2*c,rain_colors[c]);
}
static void snow(led_design_t *d) {
    clear(d);
    for(unsigned i=0;i<18;i++) {
        led_spark_t *s=&d->sparks[i];
        if(s->active || random_next(d)%100>=45)continue;
        unsigned row=random_next(d)%4,col=random_next(d)%31;bool near=false;
        for(unsigned j=0;j<18;j++)if(d->sparks[j].active) {
            int dr=(int)row-d->sparks[j].row,dc=(int)col-d->sparks[j].col;
            if(dr<0)dr=-dr;
            if(dc<0)dc=-dc;
            if((dr<=1 && dc<=1)||dr+dc<3){near=true;break;}
        }
        if(!near)*s=(led_spark_t){true,row,col,0,4+random_next(d)%4,205+random_next(d)%50,spark_colors[random_next(d)%7]};
    }
    for(unsigned i=0;i<18;i++) {
        led_spark_t *s=&d->sparks[i];if(!s->active)continue;
        float envelope=s->life<128?s->life/128.0f:(255-s->life)/127.0f;
        both(d,s->row,s->col,scaled(s->color,envelope*s->peak/255.0f));
        if(s->life+s->speed>=255)s->active=false;else s->life+=s->speed;
    }
}
static void music(led_design_t *d,unsigned pattern,const uint8_t bands[8]) {
    clear(d);
    float raw=pattern==0?bands[0]*.45f+bands[1]*.25f+bands[2]*.18f+bands[3]*.12f:bands[0]*.85f+bands[1]*.15f;
    if(raw==0) {
        unsigned v=wave(d->frame*(pattern==0?3:2));
        unsigned threshold=pattern==0?110:(pattern==1?130:140);
        raw=v>threshold?(v-threshold)*(pattern==0?3.0f:(pattern==1?4.0f:3.5f))/(255-threshold)+(pattern==0?1.0f:0.0f):0;
    }
    d->peak=raw>d->peak?raw:d->peak*.995f+raw*.005f;
    if(d->peak<2)d->peak=2;
    float norm=fminf(1,raw/d->peak);
    d->smooth=norm>d->smooth?norm:d->smooth*(pattern==0?.94f:.955f);
    bool kick=bands[0]>=3;
    if(pattern==0) {
        float radius=12+d->smooth*3,max_h=d->smooth*3.99f;
        for(unsigned c=0;c<31;c++) {
            float dist=fabsf((float)c-15);if(dist>radius)continue;
            float height=max_h*(1-.85f*(dist/radius)*(dist/radius))+(wave(c*15+d->frame*4)-128.0f)/255*.45f*(d->smooth+.3f);
            height=fmaxf(.2f,height);unsigned rows=(unsigned)height;
            for(unsigned r=0;r<=rows && r<4;r++) {
                float alpha=r==rows?height-rows:1;if(r==rows && alpha<=.05f)continue;
                if(r==0)alpha*=.75f+.25f*wave(c*12+d->frame*3)/255.0f;
                both(d,r,c,palette(c*5+r*15+d->frame*2,230,(uint8_t)(255*alpha)));
            }
        }
    } else {
        float impact=d->smooth*d->smooth;
        for(unsigned r=0;r<4;r++) {
            bool middle=r==1||r==2;
            float minimum=middle?(pattern==1?4.0f:4.5f):.8f;
            float maximum=middle?(pattern==1?31.0f:15.0f):(pattern==1?18.0f:8.5f);
            float extent=minimum+impact*(maximum-minimum);unsigned whole=(unsigned)extent;
            for(unsigned pos=0;pos<=whole && pos<(pattern==1?31U:16U);pos++) {
                float alpha=pos==whole?extent-whole:1;
                uint8_t v=wave(pos*(pattern==1?18:22)-d->frame*2);
                uint8_t bright=(uint8_t)(((v*(pattern==1?115:125)/255)+(pattern==1?140:130))*alpha);
                led_rgb_t color;
                if(kick && pos<=(pattern==1?2U:3U))color=pattern==1?(led_rgb_t){255,255,230}:(led_rgb_t){230,255,255};
                else color=palette(pattern==1?130+pos*2+d->frame:d->frame+pos*6,pattern==1?220:(kick?180:230),bright);
                if(pattern==1)both(d,r,pos,color);
                else {both(d,r,15-pos,color);both(d,r,15+pos,color);}
            }
        }
    }
}
bool led_design_render(led_design_t *d,uint32_t now,uint8_t mode,uint8_t weather,
                       uint8_t pattern,bool alert,bool valid,const uint8_t bands[8]) {
    if(mode<1 || mode>3 || (mode==1 && pattern>=6) || (mode==3 && pattern>=3) || weather>3)return false;
    bool changed=!d->initialized || d->mode!=mode || d->weather!=weather || d->pattern!=pattern || d->alert!=alert;
    if(changed) {
        uint32_t seed=d->random_state;led_design_init(d,seed);
        d->initialized=true;d->mode=mode;d->weather=weather;d->pattern=pattern;d->alert=alert;d->cycle_ms=now;
    }
    if(mode==3 && !alert && (!valid || !bands)) {
        bool redraw=changed||d->music_valid;d->music_valid=false;d->peak=2;d->smooth=0;clear(d);return redraw;
    }
    if(mode==3 && !alert && !d->music_valid)changed=true;
    d->music_valid=valid;
    if(mode==2 && weather==0 && (uint32_t)(now-d->cycle_ms)>=10000) {
        d->sunny_pattern=(d->sunny_pattern+1)%6;d->cycle_ms=now;d->frame=0;clear(d);changed=true;
    }
    unsigned period=alert?300:mode==1?basic_period(pattern):mode==2?(weather==0?basic_period(d->sunny_pattern):weather==3?25:200):pattern==0?15:12;
    if(!changed && (uint32_t)(now-d->last_ms)<period)return false;
    d->last_ms=now;
    if(alert) {
        led_rgb_t color=(d->frame%2)==0?(led_rgb_t){0,0,255}:(led_rgb_t){0,0,0};
        for(unsigned side=0;side<2;side++)for(unsigned i=0;i<124;i++)d->pixels[side][i]=color;
    } else if(mode==1)basic(d,pattern);
    else if(mode==2){if(weather==0)basic(d,d->sunny_pattern);else if(weather==3)snow(d);else rain(d);}
    else music(d,pattern,bands);
    d->frame++;return true;
}
