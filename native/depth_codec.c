/* Bounded decoder for the RVL depth format described by Andrew D. Wilson,
 * Fast Lossless Depth Image Compression, SIGCHI 2017. The database wrapper
 * signature/dimensions follow RTAB-Map's DEPTHRVL format. No external runtime.
 * This implementation validates all input reads, runs and decoded values.
 */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API
#endif
typedef struct { const uint8_t *p; size_t size, offset; uint32_t word; int remaining, error; } Reader;
static uint32_t integer(Reader *r) {
    uint32_t v=0; unsigned shift=0;
    for (;;) {
        if (!r->remaining) {
            if (r->offset+4>r->size) { r->error=1; return 0; }
            memcpy(&r->word,r->p+r->offset,4); r->offset+=4; r->remaining=8;
        }
        uint32_t nibble=r->word>>28; r->word<<=4; --r->remaining;
        if (shift>27) { r->error=2; return 0; }
        v|=(nibble&7)<<shift;
        if (!(nibble&8)) return v;
        shift+=3;
    }
}
API int decode_rvl(const uint8_t *bytes, size_t size, uint16_t *out, size_t count) {
    if (!bytes || !out || !count || count>64000000) return -1;
    Reader r={bytes,size,0,0,0,0}; size_t at=0; int previous=0;
    while (at<count) {
        uint32_t zeros=integer(&r);
        if (r.error || zeros>count-at) return -2;
        memset(out+at,0,zeros*sizeof(uint16_t)); at+=zeros;
        uint32_t nonzeros=integer(&r);
        if (r.error || nonzeros>count-at || (!zeros && !nonzeros)) return -3;
        for (uint32_t i=0;i<nonzeros;++i) {
            uint32_t positive=integer(&r);
            if (r.error || positive>131070) return -4;
            int delta=(int)(positive>>1)^-(int)(positive&1);
            int value=previous+delta;
            if (value<=0 || value>65535) return -5;
            out[at++]=(uint16_t)value; previous=value;
        }
    }
    return 0;
}
