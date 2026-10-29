#!/usr/bin/env python3
"""Frozen gate for CPU-baking NieR's four explicit skin weights, bypassing Remix API's weight stride.

Hand-computed synthetic cases, malformed inputs, and preservation of non-position attributes.
No GPU/Wine; compile candidate live_skinning.h against the real live_decode::Output type.
"""
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include <cmath>
#include <cstring>
#include <cstdio>
#include <limits>
#include "live_skinning.h"
static bool near(float a,float b){return std::fabs(a-b)<1e-4f;}
int main(){
    int failures=0;
    auto ck=[&](bool ok,const char* why){if(!ok){std::printf("FAIL %s\n",why);++failures;}};
    live_decode::Output src;
    live_decode::Vertex a{};a.position[0]=1;a.position[1]=2;a.position[2]=3;a.normal[0]=1;
    a.texcoord[0]=.125f;a.texcoord[1]=.75f;a.color=0x12345678;src.vertices={a,a};src.indices={0,1,0};
    src.bones={0,1,255,255, 1,0,255,255};src.weights={.25f,.75f,0,0, .75f,.25f,0,0};
    // Bone 0: translate +10x. Bone 1: rotate 90deg about Z, translate +20y.
    float pal[24]={1,0,0,10, 0,1,0,0, 0,0,1,0, 0,-1,0,0, 1,0,0,20, 0,0,1,0};
    std::vector<unsigned char> bytes(sizeof pal);std::memcpy(bytes.data(),pal,sizeof pal);
    auto o=src;ck(live_skinning::bake(o,bytes.data(),bytes.size()),"valid palette rejected");
    for(const auto& v:o.vertices){
      // Both vertices use .25*bone0 + .75*bone1: (.25*11+.75*-2, .25*2+.75*21, 3) = (1.25,16.25,3).
      ck(near(v.position[0],1.25f)&&near(v.position[1],16.25f)&&near(v.position[2],3),"four explicit per-vertex weights / transform");
      ck(near(v.normal[0],.316227766f)&&near(v.normal[1],.948683298f)&&near(v.normal[2],0),"normal rotation+normalization, no translation");
      ck(v.texcoord[0]==.125f&&v.texcoord[1]==.75f&&v.color==0x12345678,"UV/colour changed");
    }
    ck(o.indices==src.indices&&o.bones.empty()&&o.weights.empty(),"indices preserved / GPU skinning data cleared");
    auto full=src;full.bones={0,1,0,1, 0,1,0,1};full.weights={.1f,.2f,.3f,.4f, .2f,.3f,.4f,.1f};
    ck(live_skinning::bake(full,bytes.data(),bytes.size()),"four nonzero weights rejected");
    ck(near(full.vertices[0].position[0],3.2f)&&near(full.vertices[1].position[0],5.8f),"fourth weight must be explicit, not remainder/stride slide");
    // No normalization of weights: reproduce the game, even if a packed tuple sums below one.
    auto partial=src;partial.bones={0,255,255,255,0,255,255,255};partial.weights={.5f,0,0,0,.5f,0,0,0};
    ck(live_skinning::bake(partial,bytes.data(),bytes.size())&&near(partial.vertices[0].position[0],5.5f),"weight sum was renormalized");
    auto zero=src;for(auto& v:zero.vertices)for(float& n:v.normal)n=0;
    ck(live_skinning::bake(zero,bytes.data(),bytes.size())&&zero.vertices[0].normal[0]==0,"zero normal must remain finite");
    auto reject=[&](live_decode::Output input,const unsigned char* p,std::size_t n,const char* why){
      const auto before=input;ck(!live_skinning::bake(input,p,n),why);
      ck(input.vertices.size()==before.vertices.size()&&(!input.vertices.size()||!std::memcmp(input.vertices.data(),before.vertices.data(),input.vertices.size()*sizeof(live_decode::Vertex)))&&input.indices==before.indices&&input.bones==before.bones&&(!input.weights.size()||!std::memcmp(input.weights.data(),before.weights.data(),input.weights.size()*sizeof(float))),"failed bake mutated input");
    };
    reject(src,nullptr,bytes.size(),"null palette");reject(src,bytes.data(),47,"short palette");
    auto bad=src;bad.bones[4]=2;reject(bad,bytes.data(),bytes.size(),"active index out of range");
    bad=src;bad.weights.pop_back();reject(bad,bytes.data(),bytes.size(),"short weight array");
    bad=src;bad.bones.pop_back();reject(bad,bytes.data(),bytes.size(),"short bone array");
    bad=src;bad.weights[0]=-1;reject(bad,bytes.data(),bytes.size(),"negative weight");
    bad=src;bad.weights[0]=std::numeric_limits<float>::infinity();reject(bad,bytes.data(),bytes.size(),"nonfinite weight");
    bad=src;bad.vertices[1].position[0]=std::numeric_limits<float>::quiet_NaN();reject(bad,bytes.data(),bytes.size(),"nonfinite position");
    auto corrupt=bytes;float nan=std::numeric_limits<float>::quiet_NaN();std::memcpy(corrupt.data()+12,&nan,4);reject(src,corrupt.data(),corrupt.size(),"nonfinite active palette");
    // An unused palette slot may contain garbage, as in real capture buffers.
    auto tail=bytes;tail.insert(tail.end(),48,0xff);auto tailout=src;
    ck(live_skinning::bake(tailout,tail.data(),tail.size()),"unused garbage palette entry rejected");
    std::printf("failures=%d\n",failures);return failures?1:0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='skin-bake-') as tmp:
        w = Path(tmp)
        (w / 'h.cpp').write_text(HARNESS)
        p = subprocess.run(['g++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I', str(C),
                            str(w / 'h.cpp'), '-o', str(w / 'h')], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr[-1500:]
        p = subprocess.run([str(w / 'h')], capture_output=True, text=True)
        assert p.returncode == 0, (p.stdout + p.stderr)[-2000:]
        print(json.dumps({'passed': True, 'gate_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}))


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, subprocess.SubprocessError) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        raise SystemExit(1)
