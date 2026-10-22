#include "music_index.h"
#include <string.h>
#include <limits.h>
bool music_index_scan_to(music_index_t *idx, mp3dec_t *decoder, uint8_t *buffer,
                      size_t capacity, uint32_t start, music_index_read_fn read_fn, void *ctx, uint32_t until_ms)
{
    memset(idx,0,sizeof(*idx));idx->stride=64;
    mp3dec_init(decoder);
    size_t used=0, head=0;uint64_t offset=start;bool eof=false;
    if(capacity<4096)return false;
    for(;;) {
        /* Refill only near the end of a block, not once per MP3 frame. */
        if(!eof && used-head<2048) {
            size_t remaining=used-head;
            if(head && remaining)memmove(buffer,buffer+head,remaining);
            offset+=head;used=remaining;head=0;
            while(used<capacity) {
                ssize_t n=read_fn(ctx,buffer+used,capacity-used);
                if(n<0 || (size_t)n>capacity-used)return false;
                if(!n){eof=true;break;}
                used+=(size_t)n;
            }
        }
        size_t available=used-head;
        if(!available)break;
        mp3dec_frame_info_t info={0};
        int samples=mp3dec_decode_frame(decoder,buffer+head,(int)available,NULL,&info);
        if(info.frame_bytes<0 || (size_t)info.frame_bytes>available)return false;
        if(samples>0) {
            if(info.layer!=3 || info.hz<=0)return false;
            if(!idx->hz){idx->hz=info.hz;idx->frame_samples=samples;}
            if(idx->hz!=(uint32_t)info.hz || idx->frame_samples!=(uint32_t)samples)return false;
            if(idx->frames%idx->stride==0) {
                if(idx->count==MUSIC_INDEX_POINTS) {
                    for(unsigned i=0;i<MUSIC_INDEX_POINTS/2;i++){
                        idx->offsets[i]=idx->offsets[i*2];idx->samples[i]=idx->samples[i*2];
                    }
                    idx->count/=2;idx->stride*=2;
                }
                if(idx->frames%idx->stride==0){
                    if(offset+head+(uint32_t)info.frame_offset>UINT32_MAX)return false;
                    idx->offsets[idx->count]=(uint32_t)(offset+head)+info.frame_offset;
                    idx->samples[idx->count++]=idx->total_samples;
                }
            }
            idx->total_samples+=(unsigned)samples;idx->frames++;
            if(idx->total_samples*1000/idx->hz>UINT32_MAX)return false;
        }
        if(until_ms!=UINT32_MAX && idx->hz && idx->total_samples>(uint64_t)until_ms*idx->hz/1000)break;
        size_t consumed=info.frame_bytes>0?(size_t)info.frame_bytes:(eof?available:available-4);
        if(!consumed)return false;
        head+=consumed;
    }
    idx->ready=idx->count>0 && idx->total_samples>0;
    return idx->ready;
}
bool music_index_locate(const music_index_t *idx,uint32_t target_ms,uint32_t *offset,uint64_t *sample)
{
    if(!idx->ready || (uint64_t)target_ms*idx->hz/1000>=idx->total_samples)return false;
    uint64_t target=(uint64_t)target_ms*idx->hz/1000;
    /* Decode/discard enough preceding frames to rebuild Layer III reservoir and filters. */
    uint64_t warmup=(uint64_t)idx->frame_samples*256;
    uint64_t start=target>warmup?target-warmup:0;
    unsigned chosen=0;
    for(unsigned i=1;i<idx->count && idx->samples[i]<=start;i++)chosen=i;
    *offset=idx->offsets[chosen];*sample=idx->samples[chosen];return true;
}

bool music_index_scan(music_index_t *idx,mp3dec_t *decoder,uint8_t *buffer,size_t capacity,
                      uint32_t start,music_index_read_fn read_fn,void *ctx)
{
    return music_index_scan_to(idx,decoder,buffer,capacity,start,read_fn,ctx,UINT32_MAX);
}
static uint32_t be32(const uint8_t *p)
{
    return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
}
bool music_header_probe(const uint8_t *p,size_t n,uint64_t file_bytes,music_header_info_t *out)
{
    memset(out,0,sizeof(*out));
    if(n<4 || p[0]!=0xff || (p[1]&0xe0)!=0xe0)return false;
    unsigned version=(p[1]>>3)&3,layer=(p[1]>>1)&3,rate=(p[2]>>2)&3,bitrate=p[2]>>4;
    if(version==1 || layer!=1 || rate==3 || !bitrate || bitrate==15)return false;
    static const unsigned hz_table[]={44100,48000,32000};
    static const unsigned kbps1[]={0,32,40,48,56,64,80,96,112,128,160,192,224,256,320};
    static const unsigned kbps2[]={0,8,16,24,32,40,48,56,64,80,96,112,128,144,160};
    uint32_t hz=hz_table[rate]>>(version==3?0:version==2?1:2);
    unsigned kbps=(version==3?kbps1:kbps2)[bitrate],samples=version==3?1152:576;
    size_t frame=(version==3?144000:72000)*kbps/hz+((p[2]>>1)&1);
    if(frame>n || frame>file_bytes)return false;
    bool mono=(p[3]>>6)==3;
    size_t xing=4+(version==3?(mono?17:32):(mono?9:17));
    uint32_t count=0,bytes=0;const char *source=NULL;
    /* Xing uses the same side-info offset even for CRC-protected LAME files. */
    if(xing+12<=frame && (!memcmp(p+xing,"Xing",4)||!memcmp(p+xing,"Info",4))) {
        uint32_t flags=be32(p+xing+4);
        if(!(flags&1) || (flags&~15U))return false;
        size_t required=xing+8+4+((flags&2)?4:0)+((flags&4)?100:0)+((flags&8)?4:0);
        if(required>frame)return false;
        count=be32(p+xing+8);
        if(flags&2)bytes=be32(p+xing+12);
        source=!memcmp(p+xing,"Xing",4)?"Xing":"Info";
    } else if(36+26<=frame && !memcmp(p+36,"VBRI",4)) {
        if(p[40]!=0 || p[41]!=1)return false;
        bytes=be32(p+46);count=be32(p+50);source="VBRI";
    } else return false;
    /* Reject impossible/truncated metadata. Minimum standard MP3 frame is 24 bytes. */
    if(!count || (uint64_t)count*24>file_bytes || (bytes && (bytes<frame || bytes>file_bytes)))return false;
    uint64_t duration=(uint64_t)count*samples*1000/hz;
    if(!duration || duration>UINT32_MAX)return false;
    out->duration_ms=(uint32_t)duration;out->hz=hz;out->frame_samples=samples;out->source=source;
    return true;
}
