#!/usr/bin/env python3
"""Acceptance regressions: reject unrepresentable outputs before narrowing; decode literal LE bytes."""
import json
import sys

import test_camera_decode as gate

EXTRA = r'''
    {
        unsigned char little[128] = {};
        const auto word = [&](unsigned i, std::uint32_t bits) {
            for (unsigned j=0;j<4;++j) little[4*i+j]=static_cast<unsigned char>(bits>>(8*j));
        };
        for(unsigned i:{0u,5u,10u,15u,21u})word(i,0x3f800000u); // literal IEEE32 1
        word(16,0x3f000000u); // .5
        word(26,0xbf800000u);word(27,0xbe000000u);word(30,0xbf800000u); // -1, -.125, -1
        word(3,0x40000000u);word(7,0xc0400000u);word(11,0x40a00000u); // translation 2,-3,5
        Camera decoded{};assert(camera_decode::decode(little,sizeof little,decoded));
        assert(near(decoded[0],-2)&&near(decoded[1],3)&&near(decoded[2],-5));
        assert(near(decoded[12],90)&&near(decoded[13],2));
    }
    // Volatile input prevents constant folding from hiding an out-of-range runtime conversion.
    volatile float maximum=std::numeric_limits<float>::max();
    for(float sign:{1.f,-1.f}) {
        auto extreme=base();
        extreme[0]=extreme[2]=extreme[10]=std::sqrt(.5f);extreme[8]=-std::sqrt(.5f);
        extreme[3]=extreme[11]=sign*maximum;
        std::feclearexcept(FE_ALL_EXCEPT);
        reject(extreme.data(),sizeof extreme);
        assert(!(std::fetestexcept(FE_OVERFLOW|FE_INVALID)) && "reject position before double-to-float overflow");
    }
    {
        auto extreme=base();extreme[16]=std::numeric_limits<float>::min();extreme[21]=maximum;
        std::feclearexcept(FE_ALL_EXCEPT);
        reject(extreme.data(),sizeof extreme);
        assert(!(std::fetestexcept(FE_OVERFLOW|FE_INVALID)) && "reject aspect before double-to-float overflow");
    }
'''


def run(candidate):
    original = gate.HARNESS
    try:
        gate.HARNESS = '#include <cfenv>\n#include <cstdint>\n' + original.replace(
            '    auto f=base();Camera c{};', EXTRA + '\n    auto f=base();Camera c{};', 1)
        report = gate.run(candidate)
        report['acceptance_regressions'] = 4
        return report
    finally:
        gate.HARNESS = original


if __name__ == '__main__':
    try:
        print(json.dumps(run(sys.argv[1])))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
