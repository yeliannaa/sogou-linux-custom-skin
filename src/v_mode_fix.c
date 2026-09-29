#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <sys/stat.h>
#include <limits.h>

/* Sogou 4.2.1.145. Its native forced-vertical candidate flag already covers
 * V help/calculator, but its skin selection only follows the global setting.
 * Reload just the candidate XML on those transitions. The launcher pins the
 * native library SHA256; the symbol offsets below add a fail-open ABI guard.
 * No key logging, input rewriting, settings mutation, or binary patching. */
static void *module;
static void *resolve(const char *symbol) {
    if (!module) module=dlopen("/opt/sogoupinyin/files/lib/libSogouIme.so",RTLD_LAZY|RTLD_NOLOAD);
    void *fn=module?dlsym(module,symbol):NULL;
    if (!fn) { fprintf(stderr,"v-layout: unresolved %s\n",symbol); abort(); }
    return fn;
}
static unsigned le16(const unsigned char *p) { return p[0]|(p[1]<<8); }
static uint32_t le32(const unsigned char *p) { return le16(p)|((uint32_t)le16(p+2)<<16); }
static bool has_v_layout(const char *path) {
    static char cached_path[PATH_MAX];
    static struct stat cached_stat;
    static bool cached_result;
    struct stat st;
    if (stat(path,&st)!=0 || !S_ISREG(st.st_mode)) return false;
    if (strcmp(path,cached_path)==0 && st.st_ino==cached_stat.st_ino &&
        st.st_dev==cached_stat.st_dev && st.st_size==cached_stat.st_size &&
        st.st_mtim.tv_sec==cached_stat.st_mtim.tv_sec &&
        st.st_mtim.tv_nsec==cached_stat.st_mtim.tv_nsec) return cached_result;
    bool found=false;
    FILE *f=fopen(path,"rb");
    if (f && st.st_size>=22) {
        unsigned char end[22],entry[46];
        /* These Sogou packages have no ZIP comments. No ZIP64 is needed. */
        if (fseek(f,-22,SEEK_END)==0 && fread(end,1,22,f)==22 &&
            memcmp(end,"PK\005\006",4)==0 && le16(end+20)==0 &&
            fseek(f,(long)le32(end+16),SEEK_SET)==0) {
            unsigned count=le16(end+10);
            for (unsigned i=0;i<count;i++) {
                if (fread(entry,1,46,f)!=46 || memcmp(entry,"PK\001\002",4)!=0) break;
                unsigned len=le16(entry+28),extra=le16(entry+30),comment=le16(entry+32);
                char name[128];
                if (len<sizeof(name)) {
                    if (fread(name,1,len,f)!=len) break;
                    name[len]=0;
                    if (strcmp(name,"ime/wndComp_vmode.xml")==0) { found=true; break; }
                } else if (fseek(f,len,SEEK_CUR)!=0) break;
                if (fseek(f,extra+comment,SEEK_CUR)!=0) break;
            }
        }
    }
    if (f) fclose(f);
    snprintf(cached_path,sizeof(cached_path),"%s",path);
    cached_stat=st;
    cached_result=found;
    return found;
}
void update_comp(void *) __asm__("_ZN11t_uiWrapper10UpdateCompEv");
void update_comp(void *wrapper) {
    typedef void (*one_fn)(void *);
    one_fn original=resolve("_ZN11t_uiWrapper10UpdateCompEv");
    Dl_info symbol={0};
    if (!dladdr((void *)original,&symbol) ||
        (uintptr_t)original-(uintptr_t)symbol.dli_fbase!=0x3031e4) {
        original(wrapper); return;
    }
    unsigned char *info=*(unsigned char **)((char *)wrapper+0x138);
    void *window=*(void **)((char *)wrapper+0xe0);
    const char *path=*(const char **)((char *)wrapper+0x150);
    bool eligible=info && window && path &&
        (strcmp(path,"/opt/sogoupinyin/files/share/resources/skin/尊贵黑金/尊贵黑金.zip")==0 ||
         strcmp(path,"/opt/sogoupinyin/files/share/resources/skin/尊贵黑金-Compositing/尊贵黑金-Compositing.zip")==0) &&
        has_v_layout(path);
    if (!eligible) { original(wrapper); return; }
    int configured_style=*(int *)((char *)wrapper+0x180);
    int minheight=((int (*)(void *))resolve("_ZNK6n_sgxx11t_uiControl12GetMinHeightEv"))(window);
    bool vertical=minheight==300;
    bool target=configured_style==0 && info[15];
    if (eligible && target!=vertical) {
        int x=*(int *)((char *)window+0x3c),y=*(int *)((char *)window+0x40);
        char *zip=strdup(path);
        typedef bool (*build_fn)(void *,const char *,const char *,const char *);
        build_fn build=resolve("_ZN9t_wndComp19BuildSkinFromZipXmlEPKcS1_S1_");
        const char *xml=target?"wndComp_vmode.xml":configured_style?"wndComp_vertical.xml":"wndComp.xml";
        bool ok=build(window,zip,"ime/",xml);
        free(zip);
        ((one_fn)resolve("_ZN9t_wndComp4InitEv"))(window);
        ((one_fn)resolve("_ZN9t_wndComp15ApplyEnvSettingEv"))(window);
        ((void (*)(void *,int,int))resolve("_ZN6n_sgxx8t_wndTop7MoveWndEii"))(window,x,y);
        if (getenv("SOGOU_VMODE_FIX_TRACE"))
            fprintf(stderr,"v-layout: switch vertical=%d build=%d\n",target,ok);
    }
    original(wrapper);
}
