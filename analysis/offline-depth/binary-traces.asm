
; === colour_initial_size ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

0000000140248170 <.text+0x247170>:
   140248170:	rex push rbx
   140248172:	sub    rsp,0x80
   140248179:	mov    r10,QWORD PTR [rip+0x1537020]        # 0x14177f1a0
   140248180:	xor    ebx,ebx
   140248182:	movzx  r11d,BYTE PTR [rsp+0xc8]
   14024818b:	mov    QWORD PTR [rsp+0x70],rbx
   140248190:	mov    DWORD PTR [rsp+0x78],ebx
   140248194:	mov    DWORD PTR [rsp+0x6c],r11d
   140248199:	test   r10,r10
   14024819c:	jne    0x1402481a7
   14024819e:	mov    QWORD PTR [rsp+0x38],rbx
   1402481a3:	mov    eax,ebx
   1402481a5:	jmp    0x1402481fe
   1402481a7:	test   r11b,r11b
   1402481aa:	je     0x1402481c7
   1402481ac:	mov    eax,DWORD PTR [r10+0x3c]
   1402481b0:	xorps  xmm0,xmm0
   1402481b3:	cvtsi2ss xmm0,rax
   1402481b8:	mulss  xmm0,DWORD PTR [r10+0x80]
   1402481c1:	cvttss2si eax,xmm0
   1402481c5:	jmp    0x1402481cb
   1402481c7:	mov    eax,DWORD PTR [r10+0x3c]
   1402481cb:	mov    DWORD PTR [rsp+0x38],eax
   1402481cf:	test   r11b,r11b
   1402481d2:	je     0x1402481ef
   1402481d4:	mov    eax,DWORD PTR [r10+0x40]
   1402481d8:	xorps  xmm0,xmm0
   1402481db:	cvtsi2ss xmm0,rax
   1402481e0:	mulss  xmm0,DWORD PTR [r10+0x80]
   1402481e9:	cvttss2si eax,xmm0
   1402481ed:	jmp    0x1402481f3
   1402481ef:	mov    eax,DWORD PTR [r10+0x40]
   1402481f3:	mov    DWORD PTR [rsp+0x3c],eax
   1402481f7:	mov    eax,DWORD PTR [r10+0xc0]
   1402481fe:	mov    DWORD PTR [rsp+0x48],eax
   140248202:	mov    eax,DWORD PTR [rsp+0xb8]
   140248209:	mov    DWORD PTR [rsp+0x60],eax
   14024820d:	mov    eax,DWORD PTR [rsp+0xb0]
   140248214:	mov    DWORD PTR [rsp+0x40],edx
   140248218:	mov    rdx,rcx
   14024821b:	mov    DWORD PTR [rsp+0x44],r8d
   140248220:	lea    r8,[rsp+0x30]
   140248225:	mov    DWORD PTR [rsp+0x54],r9d
   14024822a:	mov    r9,QWORD PTR [rsp+0xc0]
   140248232:	mov    DWORD PTR [rsp+0x68],eax
   140248236:	mov    QWORD PTR [rsp+0x30],rbx
   14024823b:	mov    DWORD PTR [rsp+0x50],0x1
   140248243:	mov    DWORD PTR [rsp+0x4c],0x1
   14024824b:	mov    QWORD PTR [rsp+0x58],rbx
   140248250:	mov    DWORD PTR [rsp+0x64],ebx
   140248254:	call   0x14024ac30
   140248259:	add    rsp,0x80
   140248260:	pop    rbx
   140248261:	ret

; === depth_initial_size ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

000000014024c340 <.text+0x24b340>:
   14024c340:	rex push rbx
   14024c342:	sub    rsp,0x60
   14024c346:	mov    rax,QWORD PTR [rip+0xd286cb]        # 0x140f74a18
   14024c34d:	xor    rax,rsp
   14024c350:	mov    QWORD PTR [rsp+0x50],rax
   14024c355:	movzx  r10d,BYTE PTR [rsp+0x90]
   14024c35e:	mov    ebx,edx
   14024c360:	xor    edx,edx
   14024c362:	mov    DWORD PTR [rsp+0x48],r10d
   14024c367:	mov    r11,rcx
   14024c36a:	mov    rcx,QWORD PTR [rip+0x1532e2f]        # 0x14177f1a0
   14024c371:	test   r10d,r10d
   14024c374:	je     0x14024c3b8
   14024c376:	mov    eax,edx
   14024c378:	test   rcx,rcx
   14024c37b:	je     0x14024c380
   14024c37d:	mov    eax,DWORD PTR [rcx+0x3c]
   14024c380:	movss  xmm1,DWORD PTR [rip+0xb6e468]        # 0x140dba7f0
   14024c388:	movd   xmm0,eax
   14024c38c:	cvtdq2ps xmm0,xmm0
   14024c38f:	mulss  xmm0,xmm1
   14024c393:	cvttss2si rax,xmm0
   14024c398:	mov    DWORD PTR [rsp+0x20],eax
   14024c39c:	mov    eax,edx
   14024c39e:	test   rcx,rcx
   14024c3a1:	je     0x14024c3a6
   14024c3a3:	mov    eax,DWORD PTR [rcx+0x40]
   14024c3a6:	movd   xmm0,eax
   14024c3aa:	cvtdq2ps xmm0,xmm0
   14024c3ad:	mulss  xmm0,xmm1
   14024c3b1:	cvttss2si rax,xmm0
   14024c3b6:	jmp    0x14024c3cf
   14024c3b8:	test   rcx,rcx
   14024c3bb:	jne    0x14024c3c5
   14024c3bd:	mov    DWORD PTR [rsp+0x20],edx
   14024c3c1:	mov    eax,edx
   14024c3c3:	jmp    0x14024c3cf
   14024c3c5:	mov    eax,DWORD PTR [rcx+0x3c]
   14024c3c8:	mov    DWORD PTR [rsp+0x20],eax
   14024c3cc:	mov    eax,DWORD PTR [rcx+0x40]
   14024c3cf:	mov    DWORD PTR [rsp+0x24],eax
   14024c3d3:	test   r10d,r10d
   14024c3d6:	je     0x14024c3de
   14024c3d8:	mov    DWORD PTR [rsp+0x30],edx
   14024c3dc:	jmp    0x14024c3ef
   14024c3de:	mov    eax,edx
   14024c3e0:	test   rcx,rcx
   14024c3e3:	je     0x14024c3eb
   14024c3e5:	mov    eax,DWORD PTR [rcx+0xc0]
   14024c3eb:	mov    DWORD PTR [rsp+0x30],eax
   14024c3ef:	mov    DWORD PTR [rsp+0x28],r8d
   14024c3f4:	lea    r8,[rsp+0x20]
   14024c3f9:	mov    DWORD PTR [rsp+0x40],edx
   14024c3fd:	mov    rdx,r11
   14024c400:	mov    DWORD PTR [rsp+0x2c],ebx
   14024c404:	mov    DWORD PTR [rsp+0x34],0x1
   14024c40c:	mov    DWORD PTR [rsp+0x38],0x1
   14024c414:	mov    DWORD PTR [rsp+0x3c],r9d
   14024c419:	call   0x14024aa90
   14024c41e:	mov    rcx,QWORD PTR [rsp+0x50]
   14024c423:	xor    rcx,rsp
   14024c426:	call   0x1409d5420
   14024c42b:	add    rsp,0x60
   14024c42f:	pop    rbx
   14024c430:	ret

; === depth_resize ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

0000000140252210 <.text+0x251210>:
   140252210:	sub    rsp,0x68
   140252214:	mov    rax,QWORD PTR [rip+0xd227fd]        # 0x140f74a18
   14025221b:	xor    rax,rsp
   14025221e:	mov    QWORD PTR [rsp+0x50],rax
   140252223:	cmp    DWORD PTR [rdx+0x318],0x0
   14025222a:	mov    r9,rdx
   14025222d:	je     0x140252252
   14025222f:	cmp    DWORD PTR [rcx-0x18],0x0
   140252233:	jne    0x140252252
   140252235:	cmp    DWORD PTR [rcx-0x14],0x0
   140252239:	jne    0x140252252
   14025223b:	mov    eax,0x1
   140252240:	mov    rcx,QWORD PTR [rsp+0x50]
   140252245:	xor    rcx,rsp
   140252248:	call   0x1409d5420
   14025224d:	add    rsp,0x68
   140252251:	ret
   140252252:	mov    r10d,DWORD PTR [rcx-0x18]
   140252256:	mov    edx,DWORD PTR [rcx-0x4]
   140252259:	test   r10d,r10d
   14025225c:	je     0x1402522a4
   14025225e:	mov    eax,DWORD PTR [r9+0x3c]
   140252262:	mov    r8d,DWORD PTR [r9+0x40]
   140252266:	test   edx,edx
   140252268:	je     0x140252299
   14025226a:	movd   xmm0,eax
   14025226e:	cvtdq2ps xmm0,xmm0
   140252271:	mulss  xmm0,DWORD PTR [rip+0xb68577]        # 0x140dba7f0
   140252279:	cvttss2si rax,xmm0
   14025227e:	movd   xmm0,r8d
   140252283:	cvtdq2ps xmm0,xmm0
   140252286:	mov    DWORD PTR [rsp+0x20],eax
   14025228a:	mulss  xmm0,DWORD PTR [rip+0xb6855e]        # 0x140dba7f0
   140252292:	cvttss2si rax,xmm0
   140252297:	jmp    0x1402522ae
   140252299:	mov    DWORD PTR [rsp+0x20],eax
   14025229d:	mov    DWORD PTR [rsp+0x24],r8d
   1402522a2:	jmp    0x1402522b2
   1402522a4:	mov    eax,DWORD PTR [rcx-0x20]
   1402522a7:	mov    DWORD PTR [rsp+0x20],eax
   1402522ab:	mov    eax,DWORD PTR [rcx-0x1c]
   1402522ae:	mov    DWORD PTR [rsp+0x24],eax
   1402522b2:	mov    r8d,DWORD PTR [rcx-0x14]
   1402522b6:	test   r8d,r8d
   1402522b9:	je     0x1402522d5
   1402522bb:	mov    edx,DWORD PTR [rcx-0x4]
   1402522be:	test   edx,edx
   1402522c0:	je     0x1402522cc
   1402522c2:	mov    DWORD PTR [rsp+0x30],0x0
   1402522ca:	jmp    0x1402522dc
   1402522cc:	mov    eax,DWORD PTR [r9+0xc0]
   1402522d3:	jmp    0x1402522d8
   1402522d5:	mov    eax,DWORD PTR [rcx-0x10]
   1402522d8:	mov    DWORD PTR [rsp+0x30],eax
   1402522dc:	mov    eax,DWORD PTR [rcx-0xc]
   1402522df:	mov    DWORD PTR [rsp+0x2c],eax
   1402522e3:	mov    eax,DWORD PTR [rcx+0x28]
   1402522e6:	mov    DWORD PTR [rsp+0x28],eax
   1402522ea:	mov    eax,DWORD PTR [rcx-0x8]
   1402522ed:	mov    DWORD PTR [rsp+0x48],edx
   1402522f1:	lea    rdx,[rcx-0x28]
   1402522f5:	mov    DWORD PTR [rsp+0x38],r8d
   1402522fa:	mov    rcx,r9
   1402522fd:	lea    r8,[rsp+0x20]
   140252302:	mov    DWORD PTR [rsp+0x34],r10d
   140252307:	mov    DWORD PTR [rsp+0x44],eax
   14025230b:	call   0x140253410
   140252310:	mov    rcx,QWORD PTR [rsp+0x50]
   140252315:	xor    rcx,rsp
   140252318:	call   0x1409d5420
   14025231d:	add    rsp,0x68
   140252321:	ret

; === colour_resize_size_branch ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

00000001402526f5 <.text+0x2516f5>:
   1402526f5:	test   ecx,ecx
   1402526f7:	je     0x140252713
   1402526f9:	mov    r8d,DWORD PTR [rdx+0x3c]
   1402526fd:	xorps  xmm0,xmm0
   140252700:	cvtsi2ss xmm0,r8
   140252705:	mulss  xmm0,DWORD PTR [rdx+0x80]
   14025270d:	cvttss2si eax,xmm0
   140252711:	jmp    0x140252719
   140252713:	mov    eax,DWORD PTR [rdx+0x3c]
   140252716:	mov    r8d,eax
   140252719:	movd   xmm1,eax
   14025271d:	xorps  xmm0,xmm0
   140252720:	mov    eax,DWORD PTR [rbx-0xc]
   140252723:	cvtdq2pd xmm1,xmm1
   140252727:	cvtsi2sd xmm0,rax
   14025272c:	divsd  xmm1,xmm0
   140252730:	test   ecx,ecx
   140252732:	je     0x14025274f
   140252734:	mov    edx,DWORD PTR [rdx+0x40]
   140252737:	xorps  xmm0,xmm0
   14025273a:	cvtsi2ss xmm0,rdx
   14025273f:	mulss  xmm0,DWORD PTR [r10+0x80]
   140252748:	cvttss2si r9d,xmm0
   14025274d:	jmp    0x140252756
   14025274f:	mov    r9d,DWORD PTR [rdx+0x40]
   140252753:	mov    edx,r9d
   140252756:	mov    eax,DWORD PTR [rbx-0x38]
   140252759:	xorps  xmm0,xmm0
   14025275c:	movd   xmm2,r9d
   140252761:	cvtdq2pd xmm2,xmm2
   140252765:	cvtsi2sd xmm0,rax
   14025276a:	mulsd  xmm0,xmm1
   14025276e:	xorps  xmm1,xmm1
   140252771:	cvttsd2si rax,xmm0
   140252776:	xorps  xmm0,xmm0
   140252779:	mov    DWORD PTR [rbp+0xf],eax
   14025277c:	mov    eax,DWORD PTR [rbx-0x8]
   14025277f:	repnz

; === depth_init_callers ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

0000000140772505 <.text+0x771505>:
   140772505:	mov    r12d,0x1
   14077250b:	mov    BYTE PTR [rsp+0x20],0x0
   140772510:	mov    r9d,r12d
   140772513:	lea    rcx,[rip+0x94d196]        # 0x1410bf6b0
   14077251a:	mov    edx,r12d
   14077251d:	lea    r8d,[r12+0x1]
   140772522:	call   0x14024c340
   140772527:	test   eax,eax
   140772529:	je     0x1407731cb
   14077252f:	mov    r9d,r12d
   140772532:	mov    BYTE PTR [rsp+0x20],0x0
   140772537:	lea    r8d,[r12+0x1]
   14077253c:	mov    edx,r12d
   14077253f:	lea    rcx,[rip+0x94d17a]        # 0x1410bf6c0
   140772546:	call   0x14024c340
   14077254b:	test   eax,eax
   14077254d:	je     0x1407731cb
   140772553:	xor    r9d,r9d
   140772556:	mov    BYTE PTR [rsp+0x20],0x0
   14077255b:	lea    r8d,[r12+0x1]
   140772560:	mov    edx,r12d
   140772563:	lea    rcx,[rip+0x94d176]        # 0x1410bf6e0
   14077256a:	call   0x14024c340
   14077256f:	test   eax,eax
   140772571:	.byte 0xf

; === half_depth_init_caller ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

0000000140772632 <.text+0x771632>:
   140772632:	mov    r9d,r12d
   140772635:	mov    BYTE PTR [rsp+0x20],r12b
   14077263a:	mov    r8d,0x2
   140772640:	lea    rcx,[rip+0x94d169]        # 0x1410bf7b0
   140772647:	mov    edx,r12d
   14077264a:	call   0x14024c340
   14077264f:	test   eax,eax
   140772651:	.byte 0xf

; === depth_object_factory ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

000000014024aa90 <.text+0x249a90>:
   14024aa90:	mov    QWORD PTR [rsp+0x18],rbx
   14024aa95:	mov    QWORD PTR [rsp+0x20],rbp
   14024aa9a:	push   rsi
   14024aa9b:	sub    rsp,0x20
   14024aa9f:	cmp    DWORD PTR [rdx+0x8],0x0
   14024aaa3:	mov    rsi,r8
   14024aaa6:	mov    rbx,rdx
   14024aaa9:	je     0x14024aabd
   14024aaab:	mov    rcx,QWORD PTR [rdx]
   14024aaae:	test   rcx,rcx
   14024aab1:	je     0x14024aabd
   14024aab3:	mov    rax,QWORD PTR [rcx]
   14024aab6:	mov    edx,0x1
   14024aabb:	call   QWORD PTR [rax]
   14024aabd:	xor    ebp,ebp
   14024aabf:	mov    QWORD PTR [rsp+0x38],rdi
   14024aac4:	mov    QWORD PTR [rbx],rbp
   14024aac7:	mov    DWORD PTR [rbx+0x8],ebp
   14024aaca:	cmp    QWORD PTR [rip+0x15346cf],rbp        # 0x14177f1a0
   14024aad1:	je     0x14024ab52
   14024aad3:	mov    rcx,QWORD PTR [rip+0x1534b36]        # 0x14177f610
   14024aada:	lea    edx,[rbp+0x58]
   14024aadd:	xor    r9d,r9d
   14024aae0:	xor    r8d,r8d
   14024aae3:	call   0x1402615f0
   14024aae8:	mov    QWORD PTR [rsp+0x30],rax
   14024aaed:	mov    rdi,rax
   14024aaf0:	test   rax,rax
   14024aaf3:	je     0x14024ab52
   14024aaf5:	mov    QWORD PTR [rax+0x20],rbp
   14024aaf9:	mov    r8,rsi
   14024aafc:	mov    QWORD PTR [rax+0x38],rbp
   14024ab00:	mov    rdx,rdi
   14024ab03:	mov    QWORD PTR [rax+0x40],rbp
   14024ab07:	mov    QWORD PTR [rax+0x30],rbp
   14024ab0b:	lea    rax,[rip+0xb67376]        # 0x140db1e88
   14024ab12:	mov    QWORD PTR [rdi],rax
   14024ab15:	lea    rax,[rip+0xb6732c]        # 0x140db1e48
   14024ab1c:	mov    QWORD PTR [rdi+0x28],rax
   14024ab20:	mov    QWORD PTR [rdi+0x8],rbp
   14024ab24:	mov    QWORD PTR [rdi+0x10],rbp
   14024ab28:	mov    QWORD PTR [rdi+0x18],rbp
   14024ab2c:	mov    QWORD PTR [rdi+0x48],rbp
   14024ab30:	mov    DWORD PTR [rdi+0x50],0xffffffff
   14024ab37:	mov    rcx,QWORD PTR [rip+0x1534662]        # 0x14177f1a0
   14024ab3e:	call   0x140253410
   14024ab43:	test   eax,eax
   14024ab45:	jne    0x14024ab86
   14024ab47:	mov    rax,QWORD PTR [rdi]
   14024ab4a:	lea    edx,[rbp+0x1]
   14024ab4d:	mov    rcx,rdi
   14024ab50:	call   QWORD PTR [rax]
   14024ab52:	cmp    DWORD PTR [rbx+0x8],ebp
   14024ab55:	je     0x14024ab69
   14024ab57:	mov    rcx,QWORD PTR [rbx]
   14024ab5a:	test   rcx,rcx
   14024ab5d:	je     0x14024ab69
   14024ab5f:	mov    rax,QWORD PTR [rcx]
   14024ab62:	mov    edx,0x1
   14024ab67:	call   QWORD PTR [rax]
   14024ab69:	mov    QWORD PTR [rbx],rbp
   14024ab6c:	xor    eax,eax
   14024ab6e:	mov    DWORD PTR [rbx+0x8],ebp
   14024ab71:	mov    rdi,QWORD PTR [rsp+0x38]
   14024ab76:	mov    rbx,QWORD PTR [rsp+0x40]
   14024ab7b:	mov    rbp,QWORD PTR [rsp+0x48]
   14024ab80:	add    rsp,0x20
   14024ab84:	pop    rsi
   14024ab85:	ret
   14024ab86:	mov    QWORD PTR [rbx],rdi
   14024ab89:	mov    eax,0x1
   14024ab8e:	.byte 0xc7
   14024ab8f:	rex.XB or BYTE PTR [r9],al
	...

; === depth_backend_dispatch ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

0000000140253410 <.text+0x252410>:
   140253410:	mov    QWORD PTR [rsp+0x8],rbx
   140253415:	mov    QWORD PTR [rsp+0x10],rbp
   14025341a:	mov    QWORD PTR [rsp+0x18],rsi
   14025341f:	push   rdi
   140253420:	sub    rsp,0x20
   140253424:	mov    rsi,rcx
   140253427:	mov    rdi,r8
   14025342a:	mov    rcx,QWORD PTR [rdx+0x48]
   14025342e:	mov    rbx,rdx
   140253431:	test   rcx,rcx
   140253434:	je     0x14025343b
   140253436:	call   0x140252180
   14025343b:	xor    ebp,ebp
   14025343d:	mov    DWORD PTR [rbx+0x50],0xffffffff
   140253444:	mov    QWORD PTR [rbx+0x8],rbp
   140253448:	mov    QWORD PTR [rbx+0x10],rbp
   14025344c:	mov    QWORD PTR [rbx+0x18],rbp
   140253450:	mov    QWORD PTR [rbx+0x48],rbp
   140253454:	mov    rcx,QWORD PTR [rsi+0x2b8]
   14025345b:	test   rcx,rcx
   14025345e:	je     0x140253495
   140253460:	mov    rax,QWORD PTR [rcx]
   140253463:	mov    r8,rdi
   140253466:	mov    rdx,rbx
   140253469:	call   QWORD PTR [rax+0x50]
   14025346c:	test   eax,eax
   14025346e:	jne    0x140253499
   140253470:	mov    rcx,QWORD PTR [rbx+0x48]
   140253474:	test   rcx,rcx
   140253477:	je     0x14025347e
   140253479:	call   0x140252180
   14025347e:	mov    QWORD PTR [rbx+0x8],rbp
   140253482:	mov    QWORD PTR [rbx+0x10],rbp
   140253486:	mov    QWORD PTR [rbx+0x18],rbp
   14025348a:	mov    QWORD PTR [rbx+0x48],rbp
   14025348e:	mov    DWORD PTR [rbx+0x50],0xffffffff
   140253495:	xor    eax,eax
   140253497:	jmp    0x1402534cc
   140253499:	mov    eax,DWORD PTR [rdi+0x14]
   14025349c:	lea    rdx,[rbx+0x28]
   1402534a0:	mov    DWORD PTR [rbx+0x10],eax
   1402534a3:	lea    rcx,[rsi+0x2c8]
   1402534aa:	mov    eax,DWORD PTR [rdi+0x18]
   1402534ad:	mov    DWORD PTR [rbx+0x14],eax
   1402534b0:	mov    eax,DWORD PTR [rdi+0x8]
   1402534b3:	mov    DWORD PTR [rbx+0x50],eax
   1402534b6:	mov    eax,DWORD PTR [rdi+0x24]
   1402534b9:	mov    DWORD PTR [rbx+0x20],eax
   1402534bc:	mov    eax,DWORD PTR [rdi+0x28]
   1402534bf:	mov    DWORD PTR [rbx+0x24],eax
   1402534c2:	call   0x140252fa0
   1402534c7:	mov    eax,0x1
   1402534cc:	mov    rbx,QWORD PTR [rsp+0x30]
   1402534d1:	mov    rbp,QWORD PTR [rsp+0x38]
   1402534d6:	mov    rsi,QWORD PTR [rsp+0x40]
   1402534db:	add    rsp,0x20
   1402534df:	pop    rdi
   1402534e0:	ret

; === depth_backend_thunk ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

000000014025ce80 <.text+0x25be80>:
   14025ce80:	add    rcx,0x98
   14025ce87:	jmp    0x140258fe0

; === depth_d3d_creation ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

0000000140258fe0 <.text+0x257fe0>:
   140258fe0:	mov    QWORD PTR [rsp+0x20],rbx
   140258fe5:	push   rbp
   140258fe6:	push   rsi
   140258fe7:	push   rdi
   140258fe8:	push   r12
   140258fea:	push   r13
   140258fec:	push   r14
   140258fee:	push   r15
   140258ff0:	mov    rbp,rsp
   140258ff3:	sub    rsp,0x80
   140258ffa:	mov    rax,QWORD PTR [rip+0xd1ba17]        # 0x140f74a18
   140259001:	xor    rax,rsp
   140259004:	mov    QWORD PTR [rbp-0x10],rax
   140259008:	xor    r9d,r9d
   14025900b:	mov    QWORD PTR [rbp-0x48],rcx
   14025900f:	mov    rbx,r8
   140259012:	mov    rsi,rdx
   140259015:	mov    r14,rcx
   140259018:	xor    r8d,r8d
   14025901b:	mov    rcx,QWORD PTR [rcx+0x48]
   14025901f:	lea    edx,[r9+0x10]
   140259023:	call   0x1402615f0
   140259028:	mov    QWORD PTR [rbp-0x48],rax
   14025902c:	mov    rdi,rax
   14025902f:	test   rax,rax
   140259032:	je     0x140259177
   140259038:	xor    r12d,r12d
   14025903b:	xorps  xmm0,xmm0
   14025903e:	mov    QWORD PTR [rax],r12
   140259041:	mov    QWORD PTR [rax+0x8],r12
   140259045:	cmp    DWORD PTR [rbx+0x20],0x2
   140259049:	mov    ecx,DWORD PTR [rbx]
   14025904b:	mov    eax,DWORD PTR [rbx+0x4]
   14025904e:	mov    DWORD PTR [rbp-0x40],ecx
   140259051:	mov    DWORD PTR [rbp-0x3c],eax
   140259054:	mov    QWORD PTR [rbp-0x2c],r12
   140259058:	movdqu XMMWORD PTR [rbp-0x24],xmm0
   14025905d:	mov    DWORD PTR [rbp-0x38],0x1
   140259064:	jne    0x140259073
   140259066:	or     DWORD PTR [rbp-0x18],0x4
   14025906a:	mov    DWORD PTR [rbp-0x34],0x6
   140259071:	jmp    0x14025907a
   140259073:	mov    DWORD PTR [rbp-0x34],0x1
   14025907a:	mov    edx,DWORD PTR [rbx+0xc]
   14025907d:	mov    eax,0x27
   140259082:	test   edx,edx
   140259084:	mov    r13d,0x2d
   14025908a:	cmovne eax,r13d
   14025908e:	mov    DWORD PTR [rbp-0x30],eax
   140259091:	movsxd rax,DWORD PTR [rbx+0x10]
   140259095:	test   rax,rax
   140259098:	js     0x1402590bb
   14025909a:	lea    rcx,[r14+0x1c]
   14025909e:	lea    rcx,[rcx+rax*8]
   1402590a2:	cmp    DWORD PTR [rcx+0x4],0xffffffff
   1402590a6:	jne    0x1402590b4
   1402590a8:	add    rcx,0x8
   1402590ac:	add    rax,0x1
   1402590b0:	jns    0x1402590a2
   1402590b2:	jmp    0x1402590bb
   1402590b4:	mov    rax,QWORD PTR [rcx]
   1402590b7:	mov    QWORD PTR [rbp-0x2c],rax
   1402590bb:	test   edx,edx
   1402590bd:	mov    DWORD PTR [rbp-0x24],r12d
   1402590c1:	mov    eax,0x48
   1402590c6:	mov    DWORD PTR [rbp-0x1c],r12d
   1402590ca:	mov    ecx,0x40
   1402590cf:	lea    rdx,[rbp-0x40]
   1402590d3:	cmovne eax,ecx
   1402590d6:	mov    r9,rdi
   1402590d9:	mov    rcx,QWORD PTR [r14]
   1402590dc:	xor    r8d,r8d
   1402590df:	mov    DWORD PTR [rbp-0x20],eax
   1402590e2:	mov    rax,QWORD PTR [rcx]
   1402590e5:	call   QWORD PTR [rax+0x28]
   1402590e8:	test   eax,eax
   1402590ea:	js     0x14025916f
   1402590f0:	cmp    DWORD PTR [rbx+0xc],r12d
   1402590f4:	mov    eax,0x28
   1402590f9:	mov    QWORD PTR [rbp-0x50],r12
   1402590fd:	cmovne eax,r13d
   140259101:	mov    DWORD PTR [rbp-0x60],eax
   140259104:	cmp    DWORD PTR [rbx+0x10],r12d
   140259108:	jle    0x140259113
   14025910a:	mov    DWORD PTR [rbp-0x5c],0x5
   140259111:	jmp    0x140259130
   140259113:	cmp    DWORD PTR [rbx+0x20],0x2
   140259117:	jne    0x140259129
   140259119:	mov    DWORD PTR [rbp-0x5c],0x4
   140259120:	mov    DWORD PTR [rbp-0x4c],0x6
   140259127:	jmp    0x140259130
   140259129:	mov    DWORD PTR [rbp-0x5c],0x3
   140259130:	mov    rcx,QWORD PTR [r14]
   140259133:	lea    r9,[rdi+0x8]
   140259137:	mov    QWORD PTR [rbp-0x58],r12
   14025913b:	lea    r8,[rbp-0x60]
   14025913f:	mov    rdx,QWORD PTR [rdi]
   140259142:	mov    r10,QWORD PTR [rcx]
   140259145:	call   QWORD PTR [r10+0x50]
   140259149:	test   eax,eax
   14025914b:	js     0x14025916f
   14025914d:	mov    ecx,DWORD PTR [rbx]
   14025914f:	mov    eax,0x1
   140259154:	mov    DWORD PTR [rsi+0x8],ecx
   140259157:	mov    ecx,DWORD PTR [rbx+0x4]
   14025915a:	mov    DWORD PTR [rsi+0xc],ecx
   14025915d:	mov    ecx,DWORD PTR [rbx+0x10]
   140259160:	mov    DWORD PTR [rsi+0x18],ecx
   140259163:	mov    ecx,DWORD PTR [rbx+0xc]
   140259166:	mov    DWORD PTR [rsi+0x1c],ecx
   140259169:	mov    QWORD PTR [rsi+0x48],rdi
   14025916d:	jmp    0x140259179
   14025916f:	mov    rcx,rdi
   140259172:	call   0x140252180
   140259177:	xor    eax,eax
   140259179:	mov    rcx,QWORD PTR [rbp-0x10]
   14025917d:	xor    rcx,rsp
   140259180:	call   0x1409d5420
   140259185:	mov    rbx,QWORD PTR [rsp+0xd8]
   14025918d:	add    rsp,0x80
   140259194:	pop    r15
   140259196:	pop    r14
   140259198:	pop    r13
   14025919a:	pop    r12
   14025919c:	pop    rdi
   14025919d:	pop    rsi
   14025919e:	pop    rbp
   14025919f:	ret

; === pass_validation ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

00000001402439a0 <.text+0x2429a0>:
   1402439a0:	mov    QWORD PTR [rsp+0x10],rbx
   1402439a5:	push   rdi
   1402439a6:	sub    rsp,0x20
   1402439aa:	mov    rax,QWORD PTR [r8]
   1402439ad:	mov    rbx,rdx
   1402439b0:	mov    r9,rcx
   1402439b3:	test   rax,rax
   1402439b6:	jne    0x1402439cd
   1402439b8:	xor    edx,edx
   1402439ba:	mov    eax,0xffffffff
   1402439bf:	mov    QWORD PTR [rbx],rdx
   1402439c2:	mov    QWORD PTR [rbx+0x8],rdx
   1402439c6:	mov    DWORD PTR [rbx+0x54],eax
   1402439c9:	mov    eax,edx
   1402439cb:	jmp    0x140243a13
   1402439cd:	mov    rax,QWORD PTR [rax+0x18]
   1402439d1:	mov    QWORD PTR [rdx],rax
   1402439d4:	xor    edx,edx
   1402439d6:	cmp    DWORD PTR [r8+0x8],edx
   1402439da:	je     0x1402439e5
   1402439dc:	mov    rax,QWORD PTR [r8]
   1402439df:	mov    rcx,QWORD PTR [rax+0x18]
   1402439e3:	jmp    0x1402439e8
   1402439e5:	mov    rcx,rdx
   1402439e8:	mov    QWORD PTR [rbx+0x8],rcx
   1402439ec:	cmp    DWORD PTR [r8+0xc],edx
   1402439f0:	jne    0x1402439fe
   1402439f2:	mov    rax,QWORD PTR [r8]
   1402439f5:	mov    rcx,QWORD PTR [rax+0x18]
   1402439f9:	mov    eax,DWORD PTR [rcx+0x1c]
   1402439fc:	jmp    0x140243a03
   1402439fe:	mov    eax,0xffffffff
   140243a03:	mov    DWORD PTR [rbx+0x54],eax
   140243a06:	mov    eax,DWORD PTR [r8+0xc]
   140243a0a:	mov    DWORD PTR [rbx+0x5c],eax
   140243a0d:	mov    rax,QWORD PTR [rbx]
   140243a10:	mov    eax,DWORD PTR [rax+0x18]
   140243a13:	mov    DWORD PTR [rbx+0x4c],eax
   140243a16:	lea    rdi,[rbx+0x10]
   140243a1a:	mov    rax,QWORD PTR [r8+0x10]
   140243a1e:	test   rax,rax
   140243a21:	je     0x140243a3b
   140243a23:	mov    rax,QWORD PTR [rax+0x18]
   140243a27:	mov    QWORD PTR [rdi],rax
   140243a2a:	cmp    DWORD PTR [r8+0x18],0x0
   140243a2f:	je     0x140243a3e
   140243a31:	mov    rax,QWORD PTR [r8+0x10]
   140243a35:	mov    rcx,QWORD PTR [rax+0x18]
   140243a39:	jmp    0x140243a41
   140243a3b:	mov    QWORD PTR [rdi],rdx
   140243a3e:	mov    rcx,rdx
   140243a41:	mov    QWORD PTR [rdi+0x8],rcx
   140243a45:	mov    rax,QWORD PTR [r8+0x20]
   140243a49:	test   rax,rax
   140243a4c:	je     0x140243a67
   140243a4e:	mov    rax,QWORD PTR [rax+0x18]
   140243a52:	mov    QWORD PTR [rbx+0x20],rax
   140243a56:	cmp    DWORD PTR [r8+0x28],0x0
   140243a5b:	je     0x140243a6b
   140243a5d:	mov    rax,QWORD PTR [r8+0x20]
   140243a61:	mov    rcx,QWORD PTR [rax+0x18]
   140243a65:	jmp    0x140243a6e
   140243a67:	mov    QWORD PTR [rbx+0x20],rdx
   140243a6b:	mov    rcx,rdx
   140243a6e:	mov    QWORD PTR [rbx+0x28],rcx
   140243a72:	mov    rax,QWORD PTR [r8+0x30]
   140243a76:	test   rax,rax
   140243a79:	je     0x140243a94
   140243a7b:	mov    rax,QWORD PTR [rax+0x18]
   140243a7f:	mov    QWORD PTR [rbx+0x30],rax
   140243a83:	cmp    DWORD PTR [r8+0x38],0x0
   140243a88:	je     0x140243a98
   140243a8a:	mov    rax,QWORD PTR [r8+0x30]
   140243a8e:	mov    rcx,QWORD PTR [rax+0x18]
   140243a92:	jmp    0x140243a9b
   140243a94:	mov    QWORD PTR [rbx+0x30],rdx
   140243a98:	mov    rcx,rdx
   140243a9b:	mov    QWORD PTR [rbx+0x38],rcx
   140243a9f:	mov    rax,QWORD PTR [r8+0x40]
   140243aa3:	test   rax,rax
   140243aa6:	je     0x140243ab5
   140243aa8:	mov    rax,QWORD PTR [rax]
   140243aab:	mov    QWORD PTR [rbx+0x40],rax
   140243aaf:	mov    ecx,DWORD PTR [r8+0x48]
   140243ab3:	jmp    0x140243ac5
   140243ab5:	mov    QWORD PTR [rbx+0x40],rdx
   140243ab9:	mov    ecx,DWORD PTR [r8+0x48]
   140243abd:	test   ecx,ecx
   140243abf:	jne    0x140243b78
   140243ac5:	mov    DWORD PTR [rbx+0x48],ecx
   140243ac8:	mov    eax,DWORD PTR [r8+0x4c]
   140243acc:	mov    DWORD PTR [rbx+0x50],eax
   140243acf:	mov    eax,DWORD PTR [r8+0x50]
   140243ad3:	mov    DWORD PTR [rbx+0x58],eax
   140243ad6:	test   ecx,ecx
   140243ad8:	jne    0x140243b68
   140243ade:	mov    QWORD PTR [rsp+0x30],rsi
   140243ae3:	mov    rsi,QWORD PTR [rbx]
   140243ae6:	test   rsi,rsi
   140243ae9:	je     0x140243b1e
   140243aeb:	mov    eax,DWORD PTR [rbx+0x5c]
   140243aee:	xorps  xmm1,xmm1
   140243af1:	movsd  xmm0,QWORD PTR [rip+0xb76de7]        # 0x140dba8e0
   140243af9:	cvtsi2sd xmm1,rax
   140243afe:	call   0x140bca100
   140243b03:	mov    eax,DWORD PTR [rsi+0x8]
   140243b06:	xor    edx,edx
   140243b08:	cvttsd2si rcx,xmm0
   140243b0d:	div    ecx
   140243b0f:	xor    edx,edx
   140243b11:	mov    r9d,eax
   140243b14:	mov    eax,DWORD PTR [rsi+0xc]
   140243b17:	div    ecx
   140243b19:	mov    r8d,eax
   140243b1c:	jmp    0x140243b2a
   140243b1e:	mov    rax,QWORD PTR [r9+0x10]
   140243b22:	mov    r9d,DWORD PTR [rax+0xc]
   140243b26:	mov    r8d,DWORD PTR [rax+0x10]
   140243b2a:	mov    rsi,QWORD PTR [rsp+0x30]
   140243b2f:	mov    ecx,0x1
   140243b34:	mov    rax,QWORD PTR [rdi]
   140243b37:	test   rax,rax
   140243b3a:	je     0x140243b48
   140243b3c:	cmp    r9d,DWORD PTR [rax+0x8]
   140243b40:	jne    0x140243b78
   140243b42:	cmp    r8d,DWORD PTR [rax+0xc]
   140243b46:	jne    0x140243b78
   140243b48:	inc    ecx
   140243b4a:	add    rdi,0x10
   140243b4e:	cmp    ecx,0x4
   140243b51:	jb     0x140243b34
   140243b53:	mov    rcx,QWORD PTR [rbx+0x40]
   140243b57:	test   rcx,rcx
   140243b5a:	je     0x140243b68
   140243b5c:	cmp    DWORD PTR [rcx+0x8],r9d
   140243b60:	jne    0x140243b78
   140243b62:	cmp    DWORD PTR [rcx+0xc],r8d
   140243b66:	jne    0x140243b78
   140243b68:	mov    eax,0x1
   140243b6d:	mov    rbx,QWORD PTR [rsp+0x38]
   140243b72:	add    rsp,0x20
   140243b76:	pop    rdi
   140243b77:	ret
   140243b78:	mov    rbx,QWORD PTR [rsp+0x38]
   140243b7d:	xor    eax,eax
   140243b7f:	add    rsp,0x20
   140243b83:	pop    rdi
   140243b84:	ret

; === begin_pass ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

0000000140243b90 <.text+0x242b90>:
   140243b90:	mov    QWORD PTR [rsp+0x18],rbx
   140243b95:	push   rbp
   140243b96:	push   rsi
   140243b97:	push   rdi
   140243b98:	push   r14
   140243b9a:	push   r15
   140243b9c:	sub    rsp,0xc0
   140243ba3:	mov    rax,QWORD PTR [rip+0xd30e6e]        # 0x140f74a18
   140243baa:	xor    rax,rsp
   140243bad:	mov    QWORD PTR [rsp+0xb0],rax
   140243bb5:	xor    edi,edi
   140243bb7:	mov    r15d,r8d
   140243bba:	mov    rbp,rdx
   140243bbd:	mov    rbx,rcx
   140243bc0:	mov    DWORD PTR [rsp+0x9c],edi
   140243bc7:	cmp    QWORD PTR [rcx],rdi
   140243bca:	je     0x140243d17
   140243bd0:	cmp    QWORD PTR [rcx+0x10],rdi
   140243bd4:	je     0x140243d17
   140243bda:	mov    r8,rdx
   140243bdd:	lea    rdx,[rsp+0x40]
   140243be2:	call   0x1402439a0
   140243be7:	test   eax,eax
   140243be9:	je     0x140243d17
   140243bef:	mov    rax,QWORD PTR [rbx]
   140243bf2:	mov    rcx,QWORD PTR [rax+0x20]
   140243bf6:	test   rcx,rcx
   140243bf9:	je     0x140243d17
   140243bff:	mov    rax,QWORD PTR [rcx]
   140243c02:	lea    rdx,[rsp+0x40]
   140243c07:	mov    r8,QWORD PTR [rbx+0x10]
   140243c0b:	call   QWORD PTR [rax+0x80]
   140243c11:	test   eax,eax
   140243c13:	je     0x140243d17
   140243c19:	mov    rcx,QWORD PTR [rbx+0x8]
   140243c1d:	mov    eax,DWORD PTR [rcx+0x44c]
   140243c23:	mov    DWORD PTR [rsp+0xa4],eax
   140243c2a:	movsxd rax,DWORD PTR [rsp+0x94]
   140243c32:	mov    edx,DWORD PTR [rcx+0x450]
   140243c38:	mov    DWORD PTR [rsp+0xa8],edx
   140243c3f:	cmp    eax,0xffffffff
   140243c42:	je     0x140243d40
   140243c48:	mov    r14,QWORD PTR [rcx+0x460]
   140243c4f:	lea    rsi,[rax+rax*2]
   140243c53:	mov    rcx,QWORD PTR [rbx]
   140243c56:	mov    DWORD PTR [rsp+0xa0],edi
   140243c5d:	test   rcx,rcx
   140243c60:	je     0x140243d17
   140243c66:	mov    r8,QWORD PTR [r14+rsi*8]
   140243c6a:	test   r8,r8
   140243c6d:	je     0x140243d17
   140243c73:	cmp    edx,0xe
   140243c76:	jae    0x140243d17
   140243c7c:	mov    rcx,QWORD PTR [rcx+0x20]
   140243c80:	test   rcx,rcx
   140243c83:	je     0x140243d17
   140243c89:	mov    rax,QWORD PTR [rcx]
   140243c8c:	lea    rdx,[rsp+0xa0]
   140243c94:	call   QWORD PTR [rax+0xe0]
   140243c9a:	test   eax,eax
   140243c9c:	je     0x140243d17
   140243c9e:	mov    rax,QWORD PTR [rbx]
   140243ca1:	mov    DWORD PTR [rsp+0xa0],0x1
   140243cac:	test   rax,rax
   140243caf:	je     0x140243d17
   140243cb1:	mov    r8,QWORD PTR [r14+rsi*8]
   140243cb5:	test   r8,r8
   140243cb8:	je     0x140243d17
   140243cba:	cmp    DWORD PTR [rsp+0xa8],0xe
   140243cc2:	jae    0x140243d17
   140243cc4:	mov    rcx,QWORD PTR [rax+0x20]
   140243cc8:	test   rcx,rcx
   140243ccb:	je     0x140243d17
   140243ccd:	mov    rax,QWORD PTR [rcx]
   140243cd0:	lea    rdx,[rsp+0xa0]
   140243cd8:	call   QWORD PTR [rax+0xe0]
   140243cde:	test   eax,eax
   140243ce0:	je     0x140243d17
   140243ce2:	mov    rax,QWORD PTR [rbx+0x18]
   140243ce6:	test   rax,rax
   140243ce9:	je     0x140243d17
   140243ceb:	mov    r8,QWORD PTR [r14+rsi*8]
   140243cef:	test   r8,r8
   140243cf2:	je     0x140243d17
   140243cf4:	mov    edx,DWORD PTR [rsp+0xa8]
   140243cfb:	cmp    edx,0xe
   140243cfe:	jae    0x140243d17
   140243d00:	mov    rcx,QWORD PTR [rax+0x18]
   140243d04:	test   rcx,rcx
   140243d07:	je     0x140243d17
   140243d09:	mov    rax,QWORD PTR [rcx]
   140243d0c:	call   QWORD PTR [rax+0x68]
   140243d0f:	test   eax,eax
   140243d11:	jne    0x140243deb
   140243d17:	xor    eax,eax
   140243d19:	mov    rcx,QWORD PTR [rsp+0xb0]
   140243d21:	xor    rcx,rsp
   140243d24:	call   0x1409d5420
   140243d29:	mov    rbx,QWORD PTR [rsp+0x100]
   140243d31:	add    rsp,0xc0
   140243d38:	pop    r15
   140243d3a:	pop    r14
   140243d3c:	pop    rdi
   140243d3d:	pop    rsi
   140243d3e:	pop    rbp
   140243d3f:	ret
   140243d40:	mov    rax,QWORD PTR [rbx]
   140243d43:	mov    DWORD PTR [rsp+0xa0],edi
   140243d4a:	mov    rcx,QWORD PTR [rax+0x20]
   140243d4e:	test   rcx,rcx
   140243d51:	je     0x140243d17
   140243d53:	mov    rax,QWORD PTR [rbx+0x10]
   140243d57:	lea    rdx,[rsp+0xa0]
   140243d5f:	mov    r9,QWORD PTR [rcx]
   140243d62:	mov    r8,QWORD PTR [rax+0x28]
   140243d66:	call   QWORD PTR [r9+0xe0]
   140243d6d:	test   eax,eax
   140243d6f:	je     0x140243d17
   140243d71:	mov    rax,QWORD PTR [rbx]
   140243d74:	mov    DWORD PTR [rsp+0xa0],0x1
   140243d7f:	mov    rcx,QWORD PTR [rax+0x20]
   140243d83:	test   rcx,rcx
   140243d86:	je     0x140243d17
   140243d88:	mov    rax,QWORD PTR [rbx+0x10]
   140243d8c:	lea    rdx,[rsp+0xa0]
   140243d94:	mov    r9,QWORD PTR [rcx]
   140243d97:	mov    r8,QWORD PTR [rax+0x28]
   140243d9b:	call   QWORD PTR [r9+0xe0]
   140243da2:	test   eax,eax
   140243da4:	je     0x140243d17
   140243daa:	mov    rax,QWORD PTR [rbx+0x18]
   140243dae:	test   rax,rax
   140243db1:	je     0x140243d17
   140243db7:	mov    edx,DWORD PTR [rsp+0xa8]
   140243dbe:	cmp    edx,0xe
   140243dc1:	jae    0x140243d17
   140243dc7:	mov    rcx,QWORD PTR [rax+0x18]
   140243dcb:	test   rcx,rcx
   140243dce:	je     0x140243d17
   140243dd4:	mov    rax,QWORD PTR [rbx+0x10]
   140243dd8:	mov    r9,QWORD PTR [rcx]
   140243ddb:	mov    r8,QWORD PTR [rax+0x28]
   140243ddf:	call   QWORD PTR [r9+0x68]
   140243de3:	test   eax,eax
   140243de5:	je     0x140243d17
   140243deb:	movups xmm0,XMMWORD PTR [rbp+0x0]
   140243def:	movups XMMWORD PTR [rbx+0x60],xmm0
   140243df3:	movups xmm1,XMMWORD PTR [rbp+0x10]
   140243df7:	movups XMMWORD PTR [rbx+0x70],xmm1
   140243dfb:	movups xmm0,XMMWORD PTR [rbp+0x20]
   140243dff:	movups XMMWORD PTR [rbx+0x80],xmm0
   140243e06:	movups xmm1,XMMWORD PTR [rbp+0x30]
   140243e0a:	movups XMMWORD PTR [rbx+0x90],xmm1
   140243e11:	movups xmm0,XMMWORD PTR [rbp+0x40]
   140243e15:	movups XMMWORD PTR [rbx+0xa0],xmm0
   140243e1c:	movsd  xmm1,QWORD PTR [rbp+0x50]
   140243e21:	movsd  QWORD PTR [rbx+0xb0],xmm1
   140243e29:	test   r15d,r15d
   140243e2c:	je     0x140243e8e
   140243e2e:	mov    rcx,QWORD PTR [rbx]
   140243e31:	mov    rdx,QWORD PTR [rcx+0x20]
   140243e35:	test   rdx,rdx
   140243e38:	jne    0x140243e3e
   140243e3a:	mov    esi,edi
   140243e3c:	jmp    0x140243e4f
   140243e3e:	mov    rax,QWORD PTR [rdx]
   140243e41:	mov    rcx,rdx
   140243e44:	call   QWORD PTR [rax+0x1a8]
   140243e4a:	mov    rcx,QWORD PTR [rbx]
   140243e4d:	mov    esi,eax
   140243e4f:	mov    rcx,QWORD PTR [rcx+0x20]
   140243e53:	test   rcx,rcx
   140243e56:	je     0x140243e63
   140243e58:	mov    rax,QWORD PTR [rcx]
   140243e5b:	call   QWORD PTR [rax+0x1a0]
   140243e61:	mov    edi,eax
   140243e63:	movss  xmm0,DWORD PTR [rip+0xb769d5]        # 0x140dba840
   140243e6b:	xorps  xmm1,xmm1
   140243e6e:	movss  DWORD PTR [rsp+0x30],xmm0
   140243e74:	mov    r9d,edi
   140243e77:	movss  DWORD PTR [rsp+0x28],xmm1
   140243e7d:	xor    r8d,r8d
   140243e80:	xor    edx,edx
   140243e82:	mov    DWORD PTR [rsp+0x20],esi
   140243e86:	mov    rcx,rbx
   140243e89:	call   0x1402436c0
   140243e8e:	mov    eax,0x1
   140243e93:	jmp    0x140243d19

; === half_velocity_pass ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

000000014077edc0 <.text+0x77ddc0>:
   14077edc0:	rex push rbx
   14077edc2:	sub    rsp,0x40
   14077edc6:	xor    eax,eax
   14077edc8:	lea    r8,[rip+0x9409e1]        # 0x1410bf7b0
   14077edcf:	mov    DWORD PTR [rsp+0x30],eax
   14077edd3:	lea    rdx,[rip+0x941546]        # 0x1410c0320
   14077edda:	mov    DWORD PTR [rsp+0x28],eax
   14077edde:	xor    r9d,r9d
   14077ede1:	mov    DWORD PTR [rsp+0x20],0x1
   14077ede9:	mov    rbx,rcx
   14077edec:	call   0x140243900
   14077edf1:	xor    edx,edx
   14077edf3:	lea    rax,[rip+0x8aba76]        # 0x14102a870
   14077edfa:	mov    r8d,0xb8
   14077ee00:	mov    QWORD PTR [rsp+0x20],rax
   14077ee05:	mov    rcx,rbx
   14077ee08:	lea    r9d,[rdx+0x3]
   14077ee0c:	call   0x140244930
   14077ee11:	add    rsp,0x40
   14077ee15:	pop    rbx
   14077ee16:	ret

; === old_resize_attribution ===

/home/suraj/Projects/Nier-Automata-Rendering/analysis/input/NieRAutomata_win10.unpacked.exe:     file format pei-x86-64


Disassembly of section .text:

000000014024a9c0 <.text+0x2499c0>:
   14024a9c0:	mov    QWORD PTR [rsp+0x8],rbx
   14024a9c5:	mov    QWORD PTR [rsp+0x10],rsi
   14024a9ca:	push   rdi
   14024a9cb:	sub    rsp,0x40
   14024a9cf:	mov    rcx,QWORD PTR [rdx]
   14024a9d2:	mov    rbx,rdx
   14024a9d5:	mov    edi,r9d
   14024a9d8:	mov    esi,r8d
   14024a9db:	test   rcx,rcx
   14024a9de:	je     0x14024a9f0
   14024a9e0:	cmp    DWORD PTR [rdx+0x8],0x0
   14024a9e4:	je     0x14024a9f0
   14024a9e6:	mov    rax,QWORD PTR [rcx]
   14024a9e9:	mov    edx,0x1
   14024a9ee:	call   QWORD PTR [rax]
   14024a9f0:	movss  xmm2,DWORD PTR [rip+0xb6fdf8]        # 0x140dba7f0
   14024a9f8:	lea    r8,[rsp+0x30]
   14024a9fd:	xor    eax,eax
   14024a9ff:	movaps xmm0,xmm2
   14024aa02:	xorps  xmm3,xmm3
   14024aa05:	mov    QWORD PTR [rbx],rax
   14024aa08:	cvtsi2ss xmm3,rsi
   14024aa0d:	mov    DWORD PTR [rbx+0x8],eax
   14024aa10:	mov    r9d,0x10
   14024aa16:	mov    rax,QWORD PTR [rip+0x1534c03]        # 0x14177f620
   14024aa1d:	mov    rdx,rbx
   14024aa20:	mov    QWORD PTR [rsp+0x20],rax
   14024aa25:	xorps  xmm1,xmm1
   14024aa28:	cvtsi2ss xmm1,rdi
   14024aa2d:	divss  xmm0,xmm3
   14024aa31:	divss  xmm2,xmm1
   14024aa35:	movss  DWORD PTR [rsp+0x30],xmm0
   14024aa3b:	movss  DWORD PTR [rsp+0x34],xmm2
   14024aa41:	movss  DWORD PTR [rsp+0x38],xmm3
   14024aa47:	movss  DWORD PTR [rsp+0x3c],xmm1
   14024aa4d:	call   0x14024bc50
   14024aa52:	test   eax,eax
   14024aa54:	jne    0x14024aa66
   14024aa56:	mov    rbx,QWORD PTR [rsp+0x50]
   14024aa5b:	mov    rsi,QWORD PTR [rsp+0x58]
   14024aa60:	add    rsp,0x40
   14024aa64:	pop    rdi
   14024aa65:	ret
   14024aa66:	mov    ecx,DWORD PTR [rsp+0x70]
   14024aa6a:	mov    eax,0x1
   14024aa6f:	mov    rsi,QWORD PTR [rsp+0x58]
   14024aa74:	mov    DWORD PTR [rbx+0x10],ecx
   14024aa77:	mov    rbx,QWORD PTR [rsp+0x50]
   14024aa7c:	add    rsp,0x40
   14024aa80:	pop    rdi
   14024aa81:	ret
