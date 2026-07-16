#!/usr/bin/env python3
"""Self-contained CPUID Fault Emulation installer and GTK interface."""
import base64
import ctypes
import fcntl
import getpass
import hashlib
import io
import mmap
import os
import pwd
import re
import shutil
import signal
import struct
import subprocess
import sys
import tarfile
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

import gi
gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

APP = Path(__file__).resolve()
STATE_DIR = Path("/var/lib/hv-installer")
SOURCE_DIR = STATE_DIR / "source"
MODULE_FILE = STATE_DIR / "cpuid_fault_emulation.ko"
SERVICE_APP = Path("/usr/local/libexec/hv-installer")
SERVICE_PYTHON = Path("/usr/bin/python3")
KVM_STATE = Path("/run/hv-installer-kvm-modules")
SOURCE_ARCHIVE = (
    b'ABzY8o-A2v0{`tjYjfMSvi)lP3LdvjrBrc5J!~aD>5ObEsc-!n%g*h&ZHGgVw9Q7Zl9U~{C+D}{-Nl0-0n!qk_S`wwnn^4Hi^T$1'
    b'EOr+Q;Mn~TT!oY1i$C$xg3orhOMl^$|7+V_TYTr~JKa|M3#;|TU+`JRi5o$cU;O|4%*VgJm|EYyvAo4H^qnhrIZ2#gx}3O4IG=6J'
    b'YsT~!_txt-RvdXR3yQHkcabck!13m@B>0%{)Mz<#Zl{2`cJ|)~h~}&M{^j|>;d!Ixc~=wnItJ`O(2K*b>Hyz(8P2?#8yDr&YA2`r'
    b'M}w1hh-&}z<n7@*hkiTnhv%ci(~~!?TJ4A7`N{BzRTf^se=MQVRKLYH!DM1BXYMqxUPO&XtrlL*g5RvV$hwY#g|%s_W7B#$3CAy|'
    b'bALGr;+GQZ%keUt_%FAh2d={FMiXl0)B^gAqoeo7NE7~jW7mS2A6`Lw+{xs1Z6ok*<^X;?_+i+9zX;Q?UhJ1vWF5cxst&!{usA?%'
    b'<Ixyu-Xw5muTxAbW1xbyFP=XCmp}f8X-w?-@00(n4hZ|4{O@&pPxAk-_?!*)e;B+QIwynU;hRmPG~cWVAR$pVTU+*Kt+sc0cy!?$'
    b'pB`KuJ%C_!$b;cX0v?_24=$*_m&=9kCPBPe8(dzT9-fRY21iG4Ht#XzX%0W;154=3n|Yi#Fb$Gm>*n7u|F?U+-2AugR<HXs|Nn~5'
    b'm!RYL!Iky>Da<>VRu@C(``VX~63&8bVofH$yTnO)KKRi&efxGays%myTdjQVo|@aw=k6=HwpR8)&DF||4%6JWURKT3%bumV9i3)1'
    b'S1a2WnULGn%Dz%_wX$|A#oW`%+P0Fbmu;uH+j`lKlB<{Prnx(M*`AWCl|58?qpy{Hdo*}AQULljjcxXSP#L6U${!v6&yZLkpZ)%L'
    b'e@|tRe7*swZ3Y?*-VfD5H`a7ENI|+KmF3|2S-A7zyTj4N@LYuf?yiYR<~W1VXn4GL1RxHi&b-Oe53J4GsW)~e?)`k3Y~8@Z8Yj`x'
    b'ORRUxAWqJM>o87&D7OBnZ7jFDR^)!%<=@8gn<u~d@>?9rH2E!F$g=WVUwnBbzSu4K&6eNV@>@rK>&kDv-P$K;pPM96I9?`!<J9X5'
    b'*ZUCojm9pv2-bJcapO3MlDZ~9-n_BqS66Y6%&+Rk#y7Fqh{=d(Z!JXQVnq9EA@Yh59jt}OFGiFKyHyayVKGH(A@Yk6r6P1CiWbGA'
    b'wicpsF``s3uY#ywi09Q>cwQCaNrn9?c<fd&B6}@Fb}^#%T8P@kh&pQ_>J%gDu7#*ujHtI3q8=AVlzli0lhB>)GyfC{ShM7fg6mjF'
    b'x=_kZ@<^46JtM(~Wo)0NsEO4TBFe15tKcGn)%Kr7b1#VFc{Bq2OSZ!FEnyCLAAZWM)W7V?9>Ueo!gVW`M1^^}#O2-wKe0vp7v6ca'
    b';w@bMOBP~D=0Ui|pH3ux1KjOA^q*S`_d0MENyKq2qTtrK!73TD@q9i}ottY6SiVDZ-PKfjs(}Nb={@UX#7;<YDf&%C;<ETY6H@Hl'
    b'98yKes@7;2tX#XLs`ZGbXRv-2)HyCpvFCI@!2Bh1=<+|c|GV~oM*aND?f-6fXUERl|Lsoe$^QQ<?SGmVM}vQyUS22;fLy9DSpGf<'
    b'XUmT-llw&wZ{2*Stfw$1ykL>M54>a^wP-=<v|;^peaC~}uPw4C(j;3?YU@cIJ*lfF_4K4|J!wZz>g!3b45XUKH_&ez8ekh*U>llX'
    b't8KW8LRg=&-6qm(Lt5LA)-j}Y4QZx&w+(4KhP1vR?UjjUV?#_Wu}w{}O>MDFjS;=L@<JbnzXz(`l;vWQ@!gEtm;taeZ0_r9?(1ys'
    b'>um1pZ0_r9?(1ys>um1pZ0_r9?(1ys8`#`8u(@wwbKk(`zJbks6Px=6Hunu|?i<+LH?X;HU~@k*)w^v-+cBi|4Qa1TG#eXYYKd)X'
    b'ifw9(ZEDQtWpn!>Hg5|y4?bcd?AAE9T+FAm<@4;4ymm=mrzEdilGiKA+b+r5Daq@X<h?3uduhj%^^9HCHFjCw*kzq#m-UWa);)Gv'
    b'|JY?6WS8|&yR3)WrMy$tL+!F2YM1p;yR3)WWj)j`>!Eg854FpBs8iNM9s6?%fc8TIpd$o8I7=dhtl2bFe#MzzA^0GapSQW9pxihl'
    b'&SJHUpF|F>6iV8)A#Gwv(^Ci=)saV+Pn?(%4M~xo#GVt*;v|!}m}-fOWqfm`CC(RG8uL%&QO47JQWyn^mNrXfdfKgqZs9KDAfI?M'
    b'G2pwMEUwL|u9iFx=guOUt7+3X$|ogm{K1Lu!o<7D4E0qIMb1?e1iz~t9N#Pxe||UnoZQ`ch`YOjyKko$p_XeWn8*;8rKe8juCJ$('
    b'_bHbeC)c4i>=QjL{(y5vXD{Hnh1UCCFxC?9#-`Dq&H?K@(vt67UYWC;K^Ty4&U2$_pk{ppC&~EMFbAS#J~4nX)~1j&Z5;OsM!}@R'
    b'7v{7Jb2^1N-NKw+Va|48&Q4)YzcA-jaZ5`&p|}_9;%=~u`@t^m2s_ggpJ&o_ADVQ%bV)(+GUnU{v6gws!?VJC*22>T=hT}|r}`X9'
    b'Cgb>irU~isGIl0&?}Ia67zCp;TLiO=1q02#rOD9leXf4$Y5jC@w1<BC2z=LnNa`t&7L#6EeNGN^)%*^8chNP>vdCRzgiGM&(^Tr)'
    b'm8nmO)98L5M#<8hQ2V0gB2gQGZht3PAcu*4WBTn($G>ON!ss_aGyT4XklpmRXoJ(r04Z9C`0Y$#*)f$wy{VH{2PDFR70$CnT+cYM'
    b'TJg4C9BT?^*Lkv?VCIe|fkv2?EOB=f+#lQSEsTK%Y)<8rFx617h>98&-*&h1s22<^u|PjR#Svh1<H9N~hCUR@PR!C%%9&3+1t=Ic'
    b'NZM{cZpx)(X=L-}g}+lEB5zzvP(NGf9Uj9*lQ}Wg8VAABffIZTJft~MCM6b$V^E7g0HuNkhm+BRz_WPaM!^i?Bxhc9PZmI?dq4%5'
    b'&nEW{tBUr+5+q9{gKKp{1{N|PB=xo*%Okl?)cShx{&0VAcDTRiMxuj>r`-koH+GSGdu^RCyZY!WHLf=DwjgXWhB=jiFibtB@o{zV'
    b'A?R=%KL~@y#DjRQXY+_ni`M5IF<a{++KWA$v0uo4Y^!*D52l-Q6`)@4vmIYCnI$Of{J#CAGJW}qi89<vHnNk4Lih|OfQhXrlTDAs'
    b'oTSa4$!C%jBljQ8uS2jXE^tWCI5B^i*0;7Q^Czqno83wyx-HWR_sC`#NHjL(?B+f$Y70@l-~b@kKLTU;!AGrO66E2QwI1Ix6UDkz'
    b'I35jF8X27Yf96;ygy{W`>R;fGhVS17E}pfLQGzbZad17l;(20W-ENnuQpS?O<BV~gPOT~D!EZR#1OM>+T<Q!_^i#LG>`+m1xzTQA'
    b'hIn5nvIAH}mG~cRBQq2U!soqP1Z!)sb|GwAgKZbWb~M;dA#7KJ?H0oJG}s;!<SBE21aEgKatEBm%#8#`Mxl_C+yK<geBzrjz4>yM'
    b'h_!0In1Tq7gEZ&|+(cR$I@VYShH%u;YU0MBpEf|TjTECui9;%|L70M^>j*_r&1<Nfrr;yEtw4QKeulHFxt;sn&itk%jikJCnOos`'
    b'OBCKx6{U=Zlu<6PZ`5F_;5NYOe-*J+=ooo`61#vB#rp;QjK}$$ahSw8{;+{Rx+1V^#scJu)CNsEFts&Z#j(xW>Yb~;4b}I5$>K3B'
    b'ulfp_En{5A469SF`p!>yz9ADCmo6OY+8~#UYh)3JhjI61g14CDP<Ijaj+l7TPa!8An_&#IQmluucI{vI*s+sSU{focZ&)@=Qa{6F'
    b'`3$AP?c4}tM0q5Ba1zvlJ1ALpSWqC36%=`x)B0tdpz?g^R!+J%bs5gr1PD2LFb?cNWVS@seLS+ZMAm;ivW`Ty|9E6wfz194eb$r6'
    b'D)gCo9TFHj`;Wv(Q%hnS{+k=CE}sHVx55Zy)?A6G0+Xc+wZPJ=Ku)^4ODt7rNtFPJro!+u^*~_QuFBtv0wHl#Xq3=81dg3nH5{a>'
    b'NF@F0NTf{aSEhvUNHi5_DbSY$%2yRA%V<>+QNJoLb5%?r8dT{kuD?kf6^J3FPaxQ9eXgFCjI>u}@UlvzK($|iI#e=c`O0GzYF?$*'
    b'K}8PIbX0+GSd}F+imJf&wko!)1}o838pTwjmA<%2c%&LE&{R<=6y;f>sX$G!ZY{93D-f5e-U3Uf!rE`r%q70c%x}V0MWe{5_X1HB'
    b'T_B_Vb3`4(^vOHNGH7_YZcBCZjDqVah}451_CRjn=GY(1qKbnFsb<{3VrGU21`1&ZnHxZ;FFnQ*(FkbDsu{r#_LczyBZbPhtCXh('
    b'%Kh85i({WiA70rAX=P0w{G+{dIyc3)6>!gmj#WWy(0uA7^Pk$i?dpC&fnC;|cLL(!o?rx9I5{_<&N*cJ7Up`Txp8T(Uz&SWntNTI'
    b'>#JTbJ%92*e)vFs5}6!^d)%tm-5MEx5rzj9Ido_vEQqcgFPXHmzoXpmiJi;O{hqXQ`MKYdPA)(9d(zG2=YCImx%{5NO(YxT$>N@@'
    b'$dgTi@N@ZXJ9pSrJ%gI_6m{j{N>Xe<mL?D`=p!*X+MMgjd<@D!oWun=&>-!`fY|YZL~dD&)G$U1&i6$f>Foq~u8M!1DBnHhdwhjE'
    b'68y)9Aesde=Q?(nyk!vgaWEr$JkF;CDP=NA9?tdH0O!17ZP`VrrHRJ)<Lk7&<A`KV`YV}>M!2xdee@Pewn&mNfC`S<&N#Z9i!2?W'
    b'coBHm-4la9tkYLrX;Lt1B5^m}o@R@Qvb#(hvdSQ)X>f2$87xenFLHp8kREd8382TgdP-YQ>L^LRm#YqA6~_<<nWz<bm<FK{iSOv$'
    b'_KG^>mq(o0)x<j(Sn-;Uzg&4QUegJdD<8}9?Mmf+S-w-L{8hZB3n^FrI$qP~lP~YD?Pkegm?#)_Dq#o}4E;(N((<pWagnrGTKjvI'
    b'*!W6XC#%}6ISg`bUDH}Mqe=bg!~SEavDdVA3#hTzv~mlmX=jwi%G9*iw3Q2}>8xoh7f{n#(^f8^rn{zbTtH2V=26u2q*44RYI<wh'
    b'*7<3jHm6$=L1#@fT0_v12r5wk`lmopO+16zDiKtofZtTYaa5D=sf*CwsYHaPMGJKMkK!*y`IZR#p93LG0fDgEa)5U=2?W)KE%oJ9'
    b'6S`;`$UvQHnn4CdwF#)AsHowQT_bT+A|q=K30&1Atztz<MEyr03M8+zJC7qN2vbZI1*TYB+ZFX$v;_r<Y66RykOD_FfyFIPiKJf<'
    b'Ng}q`+SL?W)y|ce`j5esQdCV<POWN*ryBPPvs<94rtfN|I7hd=Qym>y@Ep%hMUzG~{3WXX<4|z}UZCq&ri{56B%b~w@T4pI&a21J'
    b'gZ>JMsQ*YrLI&*&9!pY3VyaA2>Uj~k_Ns{_)nOx1RU<3w=Ml*ESJ~jnpyDO_niF5~+vfv&`Svv&V-4KweRWySKiz>XpfVn9i~M)3'
    b'$9kfg8B*4CLp2rpG8<hF^<Qejw$f|K`2A0&cREIY?fu{FRxf}5R~s$`f4cwcuetv#d#4xt{{i9`@K&!h%Z;Zm;a@gUy*2*3^zvsq'
    b'36;!wbXfh?oir`D8?Rx(5%k;NEck6T`5n^MmtSHQ{t?$$*1xvkj^tx!aQ@D=8nw|sj-9ucC;ND-;`v2A$EXdwSQ#%b8=f5Oo!2b>'
    b'VZS(=i^LpRU$ua$!H*5=<#WoiTGkbAmEm4C+A-GimqkUth6{wD@ZOJ&Vh9f*_RAoAgg7XJh(mxF9hTuhh=VeS@d7D5gQsi+2*ls~'
    b'X7v&MqS5>sTM9h@KP-0m8_eC(rn^Y?NJXfD^Z}w@LeneAe^rui<IsTJRRUongk1*FMu>J9L<b={We{D2=$1kB5Td7a2C+ErTub(D'
    b'08Bfxa5;XkYY)|~rRzg}OMlK6zokgYMe^`i(Iv523azhfM%=DUJs)1w(#ZxBNS|s?Pi6c^ev04l^8TXrzh^^cZvF4Hx1ZjB`?swB'
    b'c=-&h=O7b6$eaX$4<}-AWlU}YYwCK@oMcYE6nhH{%cZ5p_ZYe+-VrmEf;$&x$%kwytZRYS)LhN$4O1b|Yaz&z7eeT1FhzOSuw1yk'
    b'27Y*pdvi&QI?bvuEd3Vl@kNHGtSjs2@Z|DG@zjyCe|j*qzI$V_H_k+IeY<JlD#TZ*JVuyMHw%m>B%Hw{4vN4S0J|qR-_RxaD`q}Z'
    b'u8MA6&FW}A1m)<d5cF?q_H>#<omJ@4^vw0Zil%owI(N>FoxQ<mXj{yVp^pimjR0N=K!*d^8GzCIV+VoY&-Zl2^w~gw+4fFK%H_$?'
    b'>EOWm{=IWNcz3wZETiq6Zo5^>;2K??ot>UvI7h?5TV_Pk1C&OXy~7KuT{Drgf1VQ2Rqo1#3<tmt4o6hDTT}9eKOSB<`)8Mj2Nt$;'
    b'r=8CO+-K*f^b*T{tp>dPez<>edTzlXd*EA(ZSz|7cW1=gkbm)yv!T^Vb30c3EsAiFKYVZ5m`j<qRUbwX%$9vPQ((P^$ZlW2$%F53'
    b'RUaW^$+^;*BE$3Z({q{`cz=#0k0zaXCFZQ<4Brn=E)Gxr%c>LY|HQu?>+gSum_hc##vh=_DZe^4KD;PjOktN<%qf6b;#L#uEZX|)'
    b'?TK^t{Xa%^nRhi~Sq*ssH})Awu^X5>(QO!G%-uYQXWt~&4Tui7T46?kthv~Cu)60MY#B`9;tjarC7IW(=P3-FQRJ?A%UecxOULBi'
    b'TE+;O#bb$RTk8%lF@g)y#t@5rkH{bq#tk-{K!jQ06t3C|VG@F4+l_Cwtivk{rk?d-21iuKL4sO3{`LSi!B;6sGLw)+T!|!>GIBJy'
    b'v->;u9><CK4DiSbzemD}Z>Ri@2_J`Zx5kiyb3AgVbsdP#yELs<8vkl>pF`@1!4Y`QPaTP)oAT&ydObhg*{^CLpnYcYlxoof1IKG{'
    b'PmV<;!84t+30a<u2z(WQ-^fu{o*HN%Ss)G}9~B%J?)oN!+JvL+udPjY)2d5Y_zg?RJi6b6=6x!t0&n|xxC(@-ScN}ly;6sW<mXm^'
    b'3O)Namft-24IYs()KBF%Ya5pOfvUfCH|x&<BiJdMZ^rn2Oy9rt@Vm#-ef$o1^Tl;^tG2`e`}3+!0oL$Eke+E+&3fqbxR$>uX!)B}'
    b'T8?8_N75UW`rs}C*01wR5`lc=9d}})o*+5f0AcV0>4M6!bOQ^)Pv9%|8{I6{ci(|HZal<T6s9<LB444TAubt%lLiopA70<=Y6MY%'
    b'P0@h>$ot8vBYZ=l6KdVyHZOpoY{yB`U|=ZX+e8+K<8$}U;@5wo@`g7V#iY}D=!xJ@ENqd~<}&uijjb^GCbsZ;$k>GtD3ZoZgQJ%p'
    b'?%@1XM5iW50CMzq0W=!q#(W7c)WR`O>~`?=pcuXlxwZ=6h>X=lVjoff6inb4NtvN%=uTE<fed1A+=4^~u?twY)D@8ZfrD7!*pKTT'
    b'bn?#yLxC4Kp%V;RT}MuV;rN*!7I!DRP%J+d<YxH#>rLxRD6$F0e2WcCgz^RX3D~AV1^GB|JfAcYQpUtv00j{#Ul!F3J{nO!)U}yb'
    b'Ox1p><r|NyL_V!;Nb4BV=zclimVLY=E2dG6V886vg#lq26{#S|L7+sXjDv&X2k>pm^*1YCE*A4B!BK`4+6xGmK_5T{k<0ZY{18|t'
    b'XBQR%1b8OX0#7?s5jQ#S-2?EQ<uUS*D`w1=Ntapn2n}8Gg-aQyLku>*C=;b1Np=!#0Y2nb+kkdcIhq!mgC$T5rvtsg@xi7A3p$D-'
    b'ixjVotcZmHdPW$Z5z1$T^BIaXn4Mtd)c;n84BQy_<|bJVzOkM?!zw8uOlAQ~@L0mZ@xc2AU#u4VbmdMkL_0^G(!~af^7{7*1VZ)C'
    b'th#-PQX{9DH_FKY1V~L7TYeZborcYDYwz%MMATs&QV?de`v%ksRXCSNNA<i`Z>*O82AwAmqAlk?BkvsDvH+U#`8Ob`Tog+16aIqN'
    b'kGPjP>o5ffy(dm`iCIbFu}Yf!7HH~l@L)HsyPMFv!IokbK9+9bfwqJfU`aMMc{XR0-+{7h2b)Atj#TsWQP0zP#it{C#~qRvFjE2_'
    b')Luwo)ARlD`Q?eFoUg=a)hpQH4sQd1!-~KJO|@w#NadLOy^dc`M-6ORz;t49mL3{I$75j~Sb%X1-3S&6-pm^d>CIGm2lYib7ie9<'
    b't+u53!rj9+R0r46*<KpFnUz*dsy2ZDLZ+8v2g0aXGkEg;_aK_HWdkc6LvQfbF4!AEh|3S8!cDD%Ttu`GuL$8N<hBn{t;T9#;U;0s'
    b'y0zf_q31;QQVanS3SC0ol=j~pEpq&_K_H&VNM$rqxkMMlupVQI<^$C#vI=YjmiXek+?z;S{0s=fjpaA5w1g+&=>5tN_b(YJ>dRZ{'
    b'#^)BqO|vs|NXrJhQ`)MdK1T^21WV=J0idq}WC1?d*|xrgGjzKM#3!=7i_Rr!T`4OBEh&oer;I-v-HnY;wT({}`h18Ur6r1i1GHid'
    b'AcEN7aK(i37?v!(>aOvYI3N!Fsan}YGb9Ii@6H*=!W)D~i-<51k#nFrx(nl=Ni&a;fC32CM5q8LM~S3L@OrVRE@1*7Fd$Yagc%de'
    b'xD<vMC-6#Pe1h>+n38c$JLS_F(}?bshe2j{S)-keBcDKb2TbuWPAgnoR+v=CZfM8HkwO8;^d!1xV$yOw5;8a{Tx)-5K5+w@sdl{h'
    b'8>?QzSmM42>u>B(Dv>p}*q%V3zM|LE_4Z`Wgy$UOYrKG~#F2397r+h1(({ZI7YndT9Gk#g_XH`c&}tfRvLwKD1Z7l1jO?LO$;3B}'
    b'ak>9t$NB!hVST45;9QR2`8K}J16F7}Ul6br*bnRm&X+=`P&)(%YaC#cu}KMX(wxmfkN`ATZ`2xDTd@juNF13DXJuaAaKXT*waX>M'
    b'Tuj=ms8Gpy!#gq6WXjvy*yZ$a_P*gJk{DLehfQTARjNZzAze7lNs_iM*|~z0f2~MMgNZBVIVY-4Cq8rzGtIaMO}e?{z^DW<7aWp_'
    b'Y&StBc`jyYeoT%JNBhp(;o#!(d^m#L&jCEpJmMo%-nWINd8^(IE{`rmW5^4+u_2cR&R}GkqSfJ%!Z!vtyI{H|8m-cb1-6TT3nur)'
    b'ecag979csF{&dDC0r?=yi@7aTZ*&<5=8J+W41~-mYHD3<Gz3pFDakscV4cM*UgbaEtTPoJ#eLWtpNj!Sf6)@YS~LGDuA~9aF=gTK'
    b'eyVLepeqQ^7P9Kb18cqXdO>B(@3l+XO_kL@b?*pkfjErKxtJYymlrm~1{V+Hk*fm!nw>n-!vhc$?F4^SPY=6`qQKL0$2=`qH0SD}'
    b'`tq(Gj;O%Zllpm7QaAxc{+_$k--D%u!-rL$b@+&`@Z;2xBhmsxT8wE09p=SqKe2A2W8f-<vWvV}?VLKEbfB)09fL(b;eflGXE7Fr'
    b'X6GF8P>jvyxWwM#PFL1=Wv)PB{KaC4XB$B-Ez6Ph>vFn4<|yoS-X7Kr&F4!E`TdT3YhPn@&d;--lf3(S6GMW~^;eWn;aw;>op4bH'
    b'un?oXs$+w$`^}ict9ZRh4r<xon}CVD&dff&K;h_{Hlj$)f&FH3mC<xtfPeuvUNE^*b#QQ9{0b2o<OG3%NN%9_RaXLf><E4iZl{<l'
    b'<`53BT=3iQnVFxe=FG;19Nf)Hcf428(UpkW=lm8O6f+==o~dFd4KT*-czl@}PdxJ%s`ELa%z^GYnxln5Y9J#!xp9F@!EcTZ58zb~'
    b'jEZZnJ@f4+wPxH_0!)PKoHdbkG(|XK{27`6<KRkUq?RjobZXZ6!uVtQg<%)IDNT>ed)w%jNXucF;oISPQ|YZ2-zid=jxb{p-VIxV'
    b'#y3SJ@Z9zmzaK&r!hq)oN{HKhu2-$+TB+xHrFyQFdNLyb8O*r$!NYVg2hl(~9B3wa;ArJG-ONRfcIW{CC{cgLYsCRo^FquEWnRiR'
    b'`a*@LQ&jKPU;=W?R5ue(0TWL}LltkyJBxNjk+`%-Y%1cH7V%9*ywW0GrU>;1_e_$WhI{MN0F!1y9|Qj{_<})5u>E`#DX1QhB^#3n'
    b'e?U<wphVn!Tu>BH7Z;_wOo(`*dK};$g!EYh#kfe}Uej{HW^NEEvllnQ%jq67r3tp-7>H1QhPZu^gwR7dH><M#;fjY&XY_;kRy_@K'
    b'z(+?=GSh5-N$Q^T0w_v*YC2LX>*(bSMyQUrhvD&BXeb3Qs4}V1Xr|l?{%<A{Q$IIfSQKNK9Kj3^fJxUcbd2JV;hy2u1b*327OI-@'
    b';z74qVOf{_HtMzGd1%dJqufo-14)>%z+9vC^deE|9#x}}UNbKtFPHNLb5}D!jG;EXs3(Jfhb$RUFu#|M;1fA_88r8Tk}I9YQgN*^'
    b'H9@%6$+j@A+M<Rs-9Iy2hQTcJ8m{2z=K3XTQ|dY9QV6_U;2Yt7oDV^;$jBmT!m{ajiIX0tP{{UPgojzk_H=8rj_R%-<7GDNLK)tJ'
    b'bPy`1?SQ0ne0g0LJG6*POimYhP8YL4P=azZ-U`7O7<pcBGuU&&O^k<MK;m(<*roFBJ$?@mnROBXd_}FXZ8JywF+N)%4A6^1wpVs`'
    b'B%{@crT!N3Fc4lB+hh@jGfSi8Ih%xQyhvdKNzBAoaF@v#{?LusE%KFn+2k7QCnT<-;2YfLgO%3aeu1UP^_iA{p$oRIA*Nw8YFbAJ'
    b'7Y(*ohbW}L;-(0#06g|~ibe>b!mYt?aF2N|;?|h9#xCEwgSI?JIsd$2)p0zbBe<^fE%vckB4Jn0116uj+}9_!q-3Y&yRlwJ?9VVz'
    b'@9o<o^uEGr>joO%@E5(XIi^tI3B1?l;9c%n&eOm~Cs)51GL8)^fBTjK2J`sgx{XHa3rKxf*YJQA_^&~gxW}IDei)<jDpX);Oz`TN'
    b'V>-ocGunHAJ4cZE6T=wM7tQE9GPjRdO={uUW^y*nbTaQ|dz-Zj{%YN<4@#%K4s>r@>9bEfL=u-+w4m5_HRpM@`traAkWjdB1h(?j'
    b'ys^5ZWtbPu?2qLHQ`SzaXTk=hoQKO<F{P>Tm_Z2TcdfZ3mFHN*(=u7)(Dj+1(tOp8%u@*5*22Xui{)GE`%^gAhC-MhXxmk4d#G4h'
    b'S#DpImnGXwl$Exorr{_UM7udx8r!X;Ni#E}$+AGs44A3C5|k##lCN|^sb$B{vh0G<8$sSG&D6sl^GYJEU#=-GBLkaTyrD>rH(q=P'
    b'nelF^p|5p@($VXf`_iamDox(vW2q)vPwMFCiH*4jk_-j(Ez`5h*h{LNk<l2n*CDp#bIot)38=!7nYROQtxkh*x6**#9FaJnTKvJf'
    b'6e_P{6OD#Cw1^YMw&2o=KpN}S-Q7}NgHG#CH8)^mB_L4<cX+SSgUxlDc5qR6LZBi5%MCS*FDs=ZeHcO1`jDRjXJpp7v0Gk9tYfNo'
    b'qqs<@)Dx~+PpH-tX6g~%Tt`s}Ri`gaf&#r&Oq8ZtzGQKDR_Hls@SC4~oeqB;I{Zh`;Y&IKosM7~I)X>h5lA{>osM`NI^svsL3;v)'
    b'Oocu}b$>}X85_lX2;rx^1aVl@s+R({Gr;X~;7$g(Qx4qC0C($U?c@i1O{<i+3%J;sRJ6EpYq!{eWh@w$l_3MUpfcvo;Ab&13WHeA'
    b'@am0nAGPA&0cnapP_76-={i^OKY&xmo%$k3oE=<A!TG)c6TfWtc7kJY5A~2uMT#hymE>VZ<2+<e+cf@$DZEgVC0vViK8O3~8V21&'
    b'b&RVVYjCF{*Oa^4RV`3-9_z9h+cEIwi+iDQ)6NPFQd25gJklN7FvYG-cRi^G(h^__LJKK)l5I24;HerMGZmBrM5&7ANac;T?Ucwz'
    b'XSSS<gQ%e$4$}3u4a7N*e46LiAZ+M+?p~9eR@=yFs)P!P<Kqb){fO)D-kv$^7-y5AmyyPr+6&Hr>p65<J_9_OA)P@2ISKuDjjGpV'
    b'4h$lvWPoo`EJ+MN%`he4F>@NXI=j;li}Dkz<(hXB!+6gI?}pCk@PCFdM0GkJ#|UpIYG>BsvG^3kb5Uf3vfy4Gn#Dk%VZy<z`<iH)'
    b'HhFw}$hboU!rIbTK?<tRIR+19v@CHlL&Pa(!|B*OgQM0-%wy{4JemO;Fdj`Wba2oWacqm0A}Ox62oE>X^MT9Hgpr3_R@*RbMCr>0'
    b'8148ML%iXYFLXBzSv&_OFz?caZm4RusU<6C!3&?m^kTs$Kfsf@uC=_L+-IYxfhY`3-aqfi1KKo;Y10sU5Q@WQ_XH07p+F@iR0$-^'
    b'%2pURayH{)PUYzQ^y-J9U&*u3{E`t6RMTmlt{W1^pEEh}bdd@RuypE;^lBpT#IYb~rBA3^_b%Vn8>xTp6!sq!U7Y(^SulCX8-%O^'
    b'Tgzfn!ViA9d{YjN^|i0=ef~UyFbfu6g8L<!1j~ew6bOjd>g?x!YbgM-^l)4+h9{@T!{fYYP0x(rD@;&^#41TqUeLhN&r*(7@#PPp'
    b'5Y^c;DB2m&4X86_3JacRr`|_ENQQ5Cjv#R1nz%VTSAYb<KOUN`;DVqe9B|yA5e<QVO|5xN>jdJnnskzad-YQSmNQ9$h;_*v3$0~('
    b'PW2qDwk%a$b{?@3@D~%H!d%F@*wDdvYr0J+qTuFizz93x_?pgg;@zuFI?ou5=^Grzi#+-UXBnY%<MnIhSl~wa_7@O@1F>7<&d`q-'
    b'5u78DkFtO-+E8mm6yCjh^n?)HwDk)bb+PJAGC_gu7Q=S)u<c^lb{@7>4BHao2zMY<k4XO5a>KkHnWyi+lohGAswhcg0~-z)WkJBz'
    b'p1iLtRelPkVaDsWmORu0>Rsy$&SXZgi8BKNXd8>|fbjb*8vH~L2y7l@IOnH(a>vy9#v=HcKr;xh;5jo?Aq3m8G`LT8j6&kMH3Khy'
    b'c4E3bn2TJ`&)MaVf3T5bSs0B8w^4k5xChJI-~t!Cv-9EE;CyKP^Pg4*W^_3^gIkhBKAQ@7vSKEhg(n4WLg=3v+sTY^D=<Bc#<p`%'
    b'mvPx;0IW}A^00FSP4|78q_HB7%jNNgQ39LAWYgjc4GlQ~3Xx2KoJOI%k=}J>3=ek~?l_#_HVkT=s4C(l3Fk{;nu*9*eIn)V2B3IX'
    b'3OC261nWQcw?(L{8sXYRDD_}Kh8>`7uprXxVHJG@EGdnRhTN>qjQkmS+fx?NSc3pKe@MQF)H6f55oez70=D^+M*Z`R`9nhm@;yP>'
    b'`M@}tJwz3TjJ#7TR#uH8GQuu<@kLe$SyEJyN&%y>B>`|m(qM_4Or!8gMe;cg+Gu2`rT25CiW`}*`r+aRV*rDMN6U&sk$7*Uo8P2|'
    b'9t_{}h>DU04XD?2$p%*#O3T5y;=k#)iR6gI!@I&s!y!rt%~G0PH&WsNu%+>DE-GCBEJ@h?#)|U0hXojmO#cFKasbdp_^phV2`;J#'
    b'T~;J?9NQtInxeZh5OhJsD)kiO?mQYdY)`U#XLoC>o<0%tS3RU*y~tb@1<p3BtvHsm^BAn7TmyvDdKI)lvArH@GH@-n_|G#3MY3B|'
    b'bPPm>@X%hBI53kT&UkVoORBwc57-4guyQ4<_J^(X2fJ?RF{a~ZShI>u$Ir81Ra!hAUYe?}Ot>yF&T^Dxr~XX&p}HGzLaLJOb(tfA'
    b'G-ih#sP}`SWoS8Dg@Tp!yOq?tN2v;*nLpRoq(9XPSQM9~;#DbY+!?{x@`er(afufWT0J{*4SB;C#lz+Y7P;m4^x*Pn=o}sH4^KwJ'
    b'`sTZ{BV2=@ZcY8qy8o4VTR;1?@2lSbzP;Vf-~ZaOcebDIfBg@*|DB=(*d_3g(6rd2GV&^TO0{0pS@;@0bSf@_=W%T;4R^pGo|OvA'
    b'iU0?TJy2_+N?;wz*0gpdgroFId-&dXpsjQbcoDgh(#As#$)XWeLY7h=+@ddATu2nP6(A2s7oc#<E-1Q-pCi;8AgiWYmCiOcWbIm0'
    b'gr-KT4+@m@MM2*q0zq}7v_%X7UWtyIUi|$5CMef=c7V=fuE2QpujR7`4OV%rh9~^yi`VMa?HLZr1&y8!WEbLr&U819ZQ<9-@jQeA'
    b'BPk3hs6+RDMEJ1+pUvN=e6KM7fb#vq{LvwGNmy8(^8Ld6y)&Y3(I{#_AM^V~#b06WtD;<dt^gk`D9oqJ_SM%4a`|n_Zx`lwD8Eyf'
    b'-=+L+VSbPD)mI8Arm?mje^g)+b=H<Vn!&OQU(8_Hh0kTM?83J)c<G{tGB|14D;e4Rf)_1VX2Ek7EVJ+}3!Yu{kOj{!dc}fg7d>IY'
    b'vy0xZ;Mv;a6(p-(Xo879W+CNMT0q2a$=d>cJU&*=D5-B#EXUSYc;7acZ3?ToaL(ZCkJBl4cCq?Q0C?T{$4&`AyGi$c7Xx$<pjQIW'
    b'MS$%RfF1(u2mq~lxz>@BH+$?*=7Hl(Eu!|RI5_-pw{pr-lA4T49bh{H(A5EY8Gw!s(9Hm}b%0I=z}5lU8Gx476|H<<pdZF!@0j5K'
    b'X~wU=TWoQBa7DuY#EY|Uz%v&c9!=plAONWP%!=~p3QY?2MVH;DMesjj5zO`OnNaym`CK_1{Mc03G0$5e9UV_)LUJ8yZ03H<KDm=B'
    b'nE2+7P%odn5>KC}&(r7W^YnT8Jbj)%PoJmH)92~)^m+O`eV#r~pQq2$=jrqGdHOtko<2{Xr_a-;%IALpPYtLk0Pp|+'
)
ACTIONS = {
    "inspect": False, "install": True, "start": True, "stop": True,
    "update": True, "uninstall": True, "disable_umip": True,
    "enable_umip": True, "bootloader": False, "disable_umip_entry": True,
    "enable_umip_entry": True, "list_games": False, "configure_games": True,
    "disable_games": True, "cpuid_test": False, "reboot": True,
}


def command(action, user, values=()):
    if action == "cpuid_test": return [sys.executable, str(APP), "--cpuid-probe"]
    if ACTIONS[action]:
        return ["pkexec", "env", "-i", f"SUDO_USER={user}", "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
                str(SERVICE_PYTHON), str(SERVICE_APP), "--backend", action, *values]
    return [sys.executable, str(APP), "--backend", action, *values]


def install_backend_copy():
    source = APP.read_bytes(); digest = hashlib.sha256(source).digest()
    try:
        installed = SERVICE_APP.read_bytes(); metadata = SERVICE_APP.stat()
        if hashlib.sha256(installed).digest() == digest and metadata.st_uid == 0 and not metadata.st_mode & 0o022: return
    except OSError:
        pass
    fd = os.memfd_create("hv-installer", os.MFD_ALLOW_SEALING)
    try:
        written = 0
        while written < len(source): written += os.write(fd, source[written:])
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        source_path = f"/proc/{os.getpid()}/fd/{fd}"
        result = subprocess.run(["pkexec", "install", "-Dm755", source_path, str(SERVICE_APP)])
        if result.returncode: raise BackendError("Could not install the privileged backend")
    finally:
        os.close(fd)
    metadata = SERVICE_APP.stat()
    if hashlib.sha256(SERVICE_APP.read_bytes()).digest() != digest or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise BackendError("Privileged backend verification failed")


def game_selection_action(appids):
    values = list(appids)
    return ("configure_games", values) if values else ("disable_games", [])


def parse_status(output):
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    return {
        "os": values.get("os", "linux"), "kernel": values.get("kernel", "unknown"),
        "umip": values.get("umip", "unknown") if values.get("umip") in {"enabled", "disabled"} else "unknown",
        "umip_arg": values.get("umip_arg", "unknown") if values.get("umip_arg") in {"present", "absent"} else "unknown",
        "installed": values.get("installed") == "1", "loaded": values.get("loaded") == "1",
        "matching": values.get("matching", "1") == "1",
        "watcher": values.get("watcher", "disabled") if values.get("watcher") in {"disabled", "enabled", "running"} else "disabled",
        "configured": {item for item in values.get("configured", "").split(",") if item},
    }


def probe_summary(returncode, module_loaded):
    if returncode == 0:
        return (("CPUID faulting works", True, "The end-to-end bypass test passed.") if module_loaded else
                ("Native support detected", True, "This CPU can fault CPUID without the emulation module."))
    if returncode == 2: return ("Module required", False, "Native CPUID faulting is unavailable on this CPU.")
    if returncode == 3: return ("CPUID faulting failed", False, "The kernel accepted the request, but CPUID did not fault.")
    if returncode == 4: return ("Unsupported architecture", False, "The diagnostic requires x86-64.")
    return ("Diagnostic failed", False, f"The isolated probe exited with status {returncode}.")


def cpuid_probe():
    if os.uname().machine.lower() not in {"x86_64", "amd64"}: return 4
    libc = ctypes.CDLL(None, use_errno=True); libc.syscall.restype = ctypes.c_long
    code = bytes.fromhex("534989d089f889f10fa241890041895804418948084189500c5bc3")
    memory = mmap.mmap(-1, len(code), prot=mmap.PROT_READ | mmap.PROT_WRITE); memory.write(code)
    address = ctypes.addressof(ctypes.c_char.from_buffer(memory)); page = address & ~(mmap.PAGESIZE - 1)
    if libc.mprotect(ctypes.c_void_p(page), ctypes.c_size_t(mmap.PAGESIZE), mmap.PROT_READ | mmap.PROT_EXEC): return 7
    cpuid_fn = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32))(address)
    def cpuid(leaf):
        registers = (ctypes.c_uint32 * 4)(); cpuid_fn(leaf, 0, registers); return registers
    native = cpuid(0x336933)
    def output(message): os.write(1, message.encode())
    output("Native leaf 0x336933: " + ", ".join(f"{name}=0x{value:08x}" for name, value in zip(("EAX", "EBX", "ECX", "EDX"), native)) + "\n")
    class SigSet(ctypes.Structure): _fields_ = [("values", ctypes.c_ulong * 16)]
    handler_type = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    class SigAction(ctypes.Structure):
        _fields_ = [("handler", handler_type), ("mask", SigSet), ("flags", ctypes.c_int), ("restorer", ctypes.c_void_p)]
    @handler_type
    def handler(_number, _info, context):
        registers = (ctypes.c_longlong * 23).from_address(context + 40)
        if registers[13] != 0x336933 or ctypes.string_at(registers[16], 2) != b"\x0f\xa2": os._exit(5)
        registers[13], registers[11], registers[14], registers[12] = 0x1337, 0, 0, 0; registers[16] += 2
    action = SigAction(); action.handler = handler; action.flags = 4
    if libc.sigemptyset(ctypes.byref(action.mask)) or libc.sigaction(signal.SIGSEGV, ctypes.byref(action), None): return 6
    if libc.syscall(158, 0x1012, 0) == -1:
        output("ARCH_SET_CPUID failed; CPUID faulting is unavailable.\n"); return 2
    output("Running isolated CPUID fault test.\n"); result = cpuid(0x336933); libc.syscall(158, 0x1012, 1)
    output(f"Spoofed EAX=0x{result[0]:08x}.\n" + ("Bypass works.\n" if result[0] == 0x1337 else "Bypass failed.\n"))
    return 0 if result[0] == 0x1337 else 3


class BackendError(RuntimeError):
    pass


def quiet(args):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def desktop_user():
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or getpass.getuser()


def as_desktop_user(args):
    if os.geteuid() != 0 or desktop_user() == "root": return args
    account = pwd.getpwnam(desktop_user())
    runtime = Path(f"/run/user/{account.pw_uid}")
    if not runtime.is_dir():
        runtime = Path(f"/tmp/hv-podman-runtime-{account.pw_uid}")
        runtime.mkdir(mode=0o700, exist_ok=True); os.chown(runtime, account.pw_uid, account.pw_gid)
    return ["runuser", "-u", account.pw_name, "--", "env", f"HOME={account.pw_dir}",
            f"XDG_RUNTIME_DIR={runtime}", *args]


def run(args, cwd=None, user=False, env=None):
    argv = as_desktop_user(args) if user else args
    print("+", " ".join(str(part) for part in argv), flush=True)
    result = subprocess.run(argv, cwd=cwd, env=env)
    if result.returncode: raise BackendError(f"Command failed with status {result.returncode}: {args[0]}")


def gaming_os():
    try: text = Path("/etc/os-release").read_text().lower()
    except OSError: return "linux"
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    os_id = values.get("id", "").strip('"')
    variant = values.get("variant_id", "").strip('"')
    names = values.get("name", "") + values.get("pretty_name", "")
    if os_id == "bazzite" or variant == "bazzite": return "bazzite"
    if os_id == "steamos" or variant == "steamdeck" or "steamos" in names: return "steamos"
    return "linux"


def bootloader():
    if Path("/etc/default/limine").is_file(): return "limine"
    if Path("/etc/default/grub").is_file(): return "grub"
    if Path("/boot/loader/entries").is_dir(): return "systemd-boot"
    if shutil.which("bootctl") and quiet(["bootctl", "is-installed"]).returncode == 0: return "systemd-boot"
    raise BackendError("No supported bootloader found")


def local_module(): return gaming_os() in {"bazzite", "steamos"}

def kernel_module_loaded(name):
    try: return any(line.startswith(name + " ") for line in Path("/proc/modules").read_text().splitlines())
    except OSError: return False


def module_loaded(): return kernel_module_loaded("cpuid_fault_emulation")


def module_installed():
    return MODULE_FILE.is_file() if local_module() else bool(shutil.which("modinfo") and quiet(["modinfo", "cpuid_fault_emulation"]).returncode == 0)


def module_matches():
    if not local_module() or not MODULE_FILE.is_file(): return True
    result = quiet(["modinfo", "-F", "vermagic", str(MODULE_FILE)]) if shutil.which("modinfo") else None
    return bool(result and result.returncode == 0 and result.stdout.split(" ", 1)[0].strip() == os.uname().release)


def configured_appids():
    unit = Path("/etc/systemd/system/hv-games.service")
    try: text = unit.read_text()
    except OSError: return set()
    match = re.search(r'^Environment="HV_GAME_APPIDS=([0-9 ]*)"$', text, re.M)
    return set(match.group(1).split()) if match else set()


def watcher_state():
    if not shutil.which("systemctl"): return "disabled"
    if quiet(["systemctl", "is-active", "--quiet", "hv-games.service"]).returncode == 0: return "running"
    return "enabled" if quiet(["systemctl", "is-enabled", "--quiet", "hv-games.service"]).returncode == 0 else "disabled"


def clearcpuid_configured():
    try:
        if gaming_os() == "bazzite" and shutil.which("rpm-ostree"):
            return "clearcpuid=514" in quiet(["rpm-ostree", "kargs"]).stdout.split()
        kind = bootloader()
        if kind == "limine": paths = [Path("/etc/default/limine")]
        elif kind == "grub": paths = [Path("/etc/default/grub")]
        else: paths = list(Path("/boot/loader/entries").glob("*.conf"))
        return any("clearcpuid=514" in path.read_text() for path in paths)
    except (OSError, BackendError): return False


def inspect_backend():
    try: cpu = Path("/proc/cpuinfo").read_text().lower()
    except OSError: cpu = ""
    values = {
        "os": gaming_os(), "kernel": os.uname().release,
        "umip": "enabled" if re.search(r"\bumip\b", cpu) else "disabled",
        "umip_arg": "present" if clearcpuid_configured() else "absent",
        "installed": int(module_installed()), "loaded": int(module_loaded()),
        "matching": int(module_matches()), "watcher": watcher_state(),
        "configured": ",".join(sorted(configured_appids(), key=int)),
    }
    for key, value in values.items(): print(f"{key}={value}")


def extract_source(destination, owner=None):
    temporary = destination.with_name(f".{destination.name}.extracting")
    shutil.rmtree(temporary, ignore_errors=True); temporary.mkdir(mode=0o755, parents=True)
    archive = tarfile.open(fileobj=io.BytesIO(base64.b85decode(SOURCE_ARCHIVE)), mode="r:gz")
    for member in archive.getmembers():
        target = (temporary / member.name).resolve()
        if temporary.resolve() not in target.parents or not (member.isfile() or member.isdir()):
            raise BackendError("Embedded module source contains an invalid path")
        archive.extract(member, temporary, filter="data")
    archive.close()
    if owner:
        for path in [temporary, *temporary.rglob("*")]: os.chown(path, owner.pw_uid, owner.pw_gid)
    shutil.rmtree(destination, ignore_errors=True); temporary.replace(destination)
    return destination


def validate_source(source):
    if not (source / "Makefile").is_file() or not (source / "dkms.conf").is_file():
        raise BackendError("Embedded module source is incomplete")
    print("Embedded module source is ready.", flush=True)


def build_container():
    system = gaming_os()
    if system not in {"bazzite", "steamos"}: raise BackendError("Container builds are only supported on Bazzite and SteamOS")
    account = pwd.getpwnam(desktop_user())
    source = extract_source(Path(account.pw_dir) / ".cache/hv-installer/module-source", account)
    validate_source(source)
    for tool in ("git", "podman", "runuser"):
        if not shutil.which(tool): raise BackendError(f"Required command not found: {tool}")
    if subprocess.run(as_desktop_user(["podman", "--version"]), stdout=subprocess.DEVNULL).returncode:
        raise BackendError("Podman is unavailable to the desktop user")
    if subprocess.run(as_desktop_user(["test", "-w", str(source)])).returncode:
        raise BackendError(f"The desktop user cannot write to {source}")
    repo = "bazzite-build-container" if system == "bazzite" else "deck-build-container"
    image = repo
    base = Path(account.pw_dir) / ".cache/hv-installer/build-containers"
    checkout = base / repo
    run(["mkdir", "-p", str(base)], user=True)
    if (checkout / ".git").is_dir(): run(["git", "-C", str(checkout), "pull", "--ff-only"], user=True)
    elif checkout.exists(): raise BackendError(f"Build path is not a Git checkout: {checkout}")
    else: run(["git", "clone", "--depth", "1", f"https://github.com/PareidoliaDev/{repo}.git", str(checkout)], user=True)
    environment = os.environ.copy(); environment.update(IMAGE_NAME=image, CONTAINER_RUNTIME="podman")
    run(["bash", "./build.sh", "--pull"], cwd=checkout, user=True, env=environment)
    podman = ["podman", "run", "--rm", "--security-opt", "label=disable"]
    if system == "steamos": podman += ["-v", "/etc:/host/etc:ro"]
    podman += ["-v", f"{source}:/work", image, "bash", "-lc",
               'build_link="/lib/modules/$KERNEL_RELEASE/build"; if [ ! -e "$build_link" ]; then mkdir -p "$(dirname "$build_link")"; ln -sfn "$KERNEL_HEADERS" "$build_link"; fi; make clean && make']
    run(podman, user=True)
    built_module = source / "cpuid_fault_emulation.ko"
    if not built_module.is_file(): raise BackendError(f"Build did not produce {built_module}")
    vermagic = quiet(["modinfo", "-F", "vermagic", str(built_module)]) if shutil.which("modinfo") else None
    if not vermagic or vermagic.returncode or vermagic.stdout.split(" ", 1)[0].strip() != os.uname().release:
        raise BackendError("The built module does not match the running kernel")
    STATE_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = STATE_DIR / ".cpuid_fault_emulation.ko.tmp"
    shutil.copyfile(built_module, temporary); temporary.chmod(0o644); temporary.replace(MODULE_FILE)
    print(f"Module compiled and installed for {os.uname().release}.")


def install_dependencies():
    kernel = os.uname().release
    if shutil.which("pacman"):
        pkgbase = Path(f"/usr/lib/modules/{kernel}/pkgbase")
        package = pkgbase.read_text().strip() if pkgbase.is_file() else "linux"
        run(["pacman", "-S", "--needed", "--noconfirm", "dkms", "base-devel", f"{package}-headers"])
    elif shutil.which("apt-get"):
        run(["apt-get", "update"]); run(["apt-get", "install", "-y", "dkms", "build-essential", f"linux-headers-{kernel}"])
    elif shutil.which("dnf"): run(["dnf", "install", "-y", "dkms", "gcc", "make", "binutils", f"kernel-devel-{kernel}"])
    elif shutil.which("yum"): run(["yum", "install", "-y", "dkms", "gcc", "make", "binutils", f"kernel-devel-{kernel}"])
    elif shutil.which("zypper"): run(["zypper", "--non-interactive", "install", "dkms", "gcc", "make", "binutils", "kernel-devel"])
    else: raise BackendError("No supported package manager found")


def install_dkms():
    if not shutil.which("dkms"): raise BackendError("DKMS is unavailable")
    status = quiet(["dkms", "status", "-m", "cpuid_fault_emulation", "-v", "0.1"])
    registered = "cpuid_fault_emulation/0.1" in status.stdout
    backup = STATE_DIR / "dkms-source-backup"
    shutil.rmtree(backup, ignore_errors=True)
    old_source = Path("/var/lib/dkms/cpuid_fault_emulation/0.1/source")
    if registered and old_source.exists(): shutil.copytree(old_source.resolve(), backup)
    source = extract_source(SOURCE_DIR)
    validate_source(source)
    run(["make", "clean"], cwd=source); run(["make"], cwd=source)
    if registered: run(["dkms", "remove", "cpuid_fault_emulation/0.1", "--all"])
    try:
        run(["dkms", "add", str(source)])
        run(["dkms", "build", "cpuid_fault_emulation/0.1", "--force"])
        run(["dkms", "install", "cpuid_fault_emulation/0.1", "--force"])
    except Exception:
        quiet(["dkms", "remove", "cpuid_fault_emulation/0.1", "--all"])
        if backup.is_dir():
            run(["dkms", "add", str(backup)])
            run(["dkms", "build", "cpuid_fault_emulation/0.1", "--force"])
            run(["dkms", "install", "cpuid_fault_emulation/0.1", "--force"])
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
    print("Module installed successfully.")


def install_backend():
    if local_module(): build_container()
    else: install_dependencies(); install_dkms()


def update_backend():
    build_container() if local_module() else install_dkms()


@contextmanager
def module_lock():
    with Path("/run/hv-installer.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def restore_kvm(modules):
    for name in reversed(modules):
        if not kernel_module_loaded(name): run(["modprobe", name])


def _start_backend():
    if not module_installed(): raise BackendError("The module is not installed")
    if module_loaded(): print("The module is already running."); return False
    if KVM_STATE.is_file():
        restore_kvm(KVM_STATE.read_text().split()); KVM_STATE.unlink()
    if not module_matches(): raise BackendError(f"The module does not match kernel {os.uname().release}")
    removed = []
    try:
        for name in ("kvm_amd", "kvm"):
            if kernel_module_loaded(name): run(["modprobe", "-r", name]); removed.append(name)
        KVM_STATE.write_text("\n".join(removed) + "\n")
        run(["insmod", str(MODULE_FILE)] if local_module() else ["modprobe", "cpuid_fault_emulation"])
        if not module_loaded(): raise BackendError("The module failed to start")
    except Exception:
        if module_loaded():
            try: run(["rmmod", "cpuid_fault_emulation"] if local_module() else ["modprobe", "-r", "cpuid_fault_emulation"])
            except Exception: raise BackendError("Startup failed and the module could not be rolled back")
        restore_kvm(removed); KVM_STATE.unlink(missing_ok=True); raise
    print("Module started successfully.")
    return True


def _stop_backend():
    was_loaded = module_loaded()
    if was_loaded: run(["rmmod", "cpuid_fault_emulation"] if local_module() else ["modprobe", "-r", "cpuid_fault_emulation"])
    if KVM_STATE.is_file(): modules = KVM_STATE.read_text().split()
    elif was_loaded: modules = ["kvm_amd", "kvm"]
    else: print("The module is already stopped."); return
    restore_kvm(modules)
    KVM_STATE.unlink(missing_ok=True)
    if module_loaded(): raise BackendError("The module failed to stop")
    print("Module stopped successfully.")


def start_backend():
    with module_lock(): return _start_backend()


def stop_backend():
    with module_lock(): _stop_backend()


def disable_games_backend():
    unit = Path("/etc/systemd/system/hv-games.service")
    if unit.exists() and shutil.which("systemctl"): run(["systemctl", "disable", "--now", "hv-games.service"])
    print("Automatic activation is disabled. The game selection was retained.")


def uninstall_backend():
    if watcher_state() != "disabled": disable_games_backend()
    with module_lock():
        if module_loaded() or KVM_STATE.is_file(): _stop_backend()
        if local_module():
            if MODULE_FILE.exists(): MODULE_FILE.unlink(); print(f"Removed {MODULE_FILE}.")
            else: print("No compiled module was found.")
            return
        if not shutil.which("dkms"): raise BackendError("DKMS is unavailable")
        run(["dkms", "remove", "cpuid_fault_emulation/0.1", "--all"])
        if shutil.which("depmod"): run(["depmod"])
        print("Module uninstalled successfully.")


def replace_kernel_arg(text, kind, present):
    token = "clearcpuid=514"
    if kind == "grub":
        pattern = re.compile(r'^(GRUB_CMDLINE_LINUX_DEFAULT=)(?:"([^"]*)"|(.*))$', re.M)
        match = pattern.search(text)
        args = (match.group(2) if match and match.group(2) is not None else match.group(3) if match else "") or ""
        values = [value for value in args.split() if value != token]
        if present: values.append(token)
        line = f'GRUB_CMDLINE_LINUX_DEFAULT="{" ".join(values)}"'
        return pattern.sub(line, text, count=1) if match else text.rstrip() + "\n" + line + "\n"
    lines = text.splitlines()
    if kind == "limine":
        lines = [line for line in lines if line.strip() != "KERNEL_CMDLINE[default]+=clearcpuid=514"]
        if present: lines.append("KERNEL_CMDLINE[default]+=clearcpuid=514")
    else:
        changed = False
        for index, line in enumerate(lines):
            if re.match(r"^\s*options(?:\s|$)", line):
                values = [value for value in line.split() if value != token]
                if present: values.append(token)
                lines[index] = " ".join(values); changed = True; break
        if not changed: raise BackendError("No options line was found in the boot entry")
    return "\n".join(lines) + "\n"


def atomic_write(path, text):
    metadata = path.stat(); temporary = path.with_name(f".{path.name}.hv-installer.tmp")
    temporary.write_text(text); temporary.chmod(metadata.st_mode & 0o777); os.chown(temporary, metadata.st_uid, metadata.st_gid)
    temporary.replace(path)


def update_grub():
    if shutil.which("update-grub"): run(["update-grub"])
    elif shutil.which("grub-mkconfig"): run(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
    elif shutil.which("grub2-mkconfig"):
        output = "/boot/grub2/grub.cfg" if Path("/boot/grub2").is_dir() else "/boot/grub/grub.cfg"
        run(["grub2-mkconfig", "-o", output])
    else: raise BackendError("No GRUB configuration generator was found")


def valid_boot_entry(value):
    entry = Path(value).resolve(); parent = Path("/boot/loader/entries").resolve()
    if entry.parent != parent or entry.suffix != ".conf" or not entry.is_file(): raise BackendError(f"Invalid boot entry: {value}")
    return entry


def change_umip(present, entry_value=None):
    token = "clearcpuid=514"
    if gaming_os() == "bazzite":
        if not shutil.which("rpm-ostree"): raise BackendError("rpm-ostree is unavailable")
        configured = clearcpuid_configured()
        if configured != present: run(["rpm-ostree", "kargs", "--append=" + token if present else "--delete=" + token])
    else:
        kind = bootloader()
        if kind == "systemd-boot": path = valid_boot_entry(entry_value or "")
        else: path = Path("/etc/default/limine" if kind == "limine" else "/etc/default/grub")
        if kind == "limine" and not shutil.which("limine-update"): raise BackendError("limine-update is unavailable")
        if kind == "grub" and not any(shutil.which(tool) for tool in ("update-grub", "grub-mkconfig", "grub2-mkconfig")):
            raise BackendError("No GRUB configuration generator was found")
        original = path.read_text(); changed = replace_kernel_arg(original, kind, present)
        if changed != original:
            atomic_write(path, changed)
            try:
                if kind == "limine": run(["limine-update"])
                elif kind == "grub": update_grub()
            except Exception:
                atomic_write(path, original)
                try:
                    if kind == "limine": run(["limine-update"])
                    elif kind == "grub": update_grub()
                except Exception:
                    pass
                raise
    print(("Applied " if present else "Removed ") + token + ". Please restart.")


def steam_home(): return Path(pwd.getpwnam(desktop_user()).pw_dir)


def vdf_string(data, position):
    end = data.find(b"\0", position)
    if end < 0: raise ValueError("Unterminated VDF string")
    return data[position:end].decode("utf-8", errors="replace"), end + 1


def vdf_object(data, position=0):
    result = {}
    while position < len(data):
        value_type = data[position]; position += 1
        if value_type in (8, 10): return result, position
        key, position = vdf_string(data, position)
        if value_type == 0: value, position = vdf_object(data, position)
        elif value_type == 1: value, position = vdf_string(data, position)
        elif value_type in (2, 3, 4, 6): value = struct.unpack_from("<I", data, position)[0]; position += 4
        elif value_type in (7, 9): value = struct.unpack_from("<Q", data, position)[0]; position += 8
        else: raise ValueError(f"Unsupported VDF value type {value_type}")
        result[key] = value
    return result, position


def shortcut_games():
    roots = [steam_home() / ".local/share/Steam", steam_home() / ".steam/steam"]
    games = {}
    for root in roots:
        for path in (root / "userdata").glob("*/config/shortcuts.vdf"):
            try: entries = vdf_object(path.read_bytes())[0].get("shortcuts", {})
            except (OSError, ValueError, struct.error): continue
            for entry in entries.values():
                normalized = {str(key).casefold(): value for key, value in entry.items()}
                appid, name = normalized.get("appid"), normalized.get("appname")
                if isinstance(appid, int) and isinstance(name, str) and name: games[str(appid)] = name.replace("\t", " ").replace("\n", " ")
    return games


def list_games_backend():
    games = shortcut_games()
    if not games: raise BackendError(f"No Steam shortcuts were found for {desktop_user()}")
    for appid, name in games.items(): print(f"{appid}\t{name}")


def steam_log():
    for path in (steam_home() / ".local/share/Steam/logs/gameprocess_log.txt", steam_home() / ".steam/steam/logs/gameprocess_log.txt"):
        if path.is_file(): return path
    return steam_home() / ".local/share/Steam/logs/gameprocess_log.txt"


def unit_escape(value): return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def configure_games_backend(appids):
    if not appids: raise BackendError("Select at least one Steam shortcut")
    if any(not value.isdigit() or int(value) > 0xffffffff for value in appids): raise BackendError("Invalid shortcut AppID")
    unit = Path("/etc/systemd/system/hv-games.service")
    contents = f'''[Unit]\nDescription=CPUID Fault Emulation Steam game watcher\nAfter=local-fs.target\n\n[Service]\nType=simple\nEnvironment="HV_GAME_APPIDS={' '.join(appids)}"\nEnvironment="HV_STEAM_LOG={unit_escape(steam_log())}"\nExecStart="{unit_escape(SERVICE_PYTHON)}" "{unit_escape(SERVICE_APP)}" --watch\nRestart=on-failure\nRestartSec=3\n\n[Install]\nWantedBy=multi-user.target\n'''
    temporary = unit.with_suffix(".tmp"); temporary.write_text(contents); temporary.chmod(0o644); temporary.replace(unit)
    run(["systemctl", "daemon-reload"]); run(["systemctl", "enable", "hv-games.service"]); run(["systemctl", "restart", "hv-games.service"])
    print(f"Automatic activation enabled for {len(appids)} shortcut(s).")


def process_start(pid):
    try: return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError): return None


def shortcut_appid(game_id, pid, configured, require_environment=False):
    numeric = int(game_id)
    logged = [str((numeric >> 32) & 0xffffffff), str(numeric)]
    environment_ids = []
    try:
        environment = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        for item in environment:
            key, separator, value = item.partition(b"=")
            if separator and key in {b"SteamAppId", b"SteamGameId", b"PRESSURE_VESSEL_APP_ID"} and value.isdigit():
                found = int(value); environment_ids += [str((found >> 32) & 0xffffffff), str(found)]
    except OSError:
        pass
    candidates = environment_ids if require_environment else logged + environment_ids
    return next((value for value in candidates if value in configured), None)


def watch_games():
    appids = set(os.environ.get("HV_GAME_APPIDS", "").split()); log = Path(os.environ.get("HV_STEAM_LOG", ""))
    if not appids or not str(log): raise BackendError("Watcher configuration is missing")
    tracked = {}; owns = Path("/run/hv-games-owns-module"); stopping = False
    def stop_signal(*_):
        nonlocal stopping; stopping = True
    signal.signal(signal.SIGTERM, stop_signal); signal.signal(signal.SIGINT, stop_signal)
    def handle(line, historical=False):
        add = re.search(r"AppID\s+(\d+)\s+adding\s+PID\s+(\d+)\s+as\s+a\s+tracked\s+process", line)
        remove = re.search(r"AppID\s+(\d+)\s+no\s+longer\s+tracking\s+PID\s+(\d+)", line)
        match = add or remove
        if not match: return
        key = (match.group(1), match.group(2))
        if remove: tracked.pop(key, None); return
        if shortcut_appid(match.group(1), match.group(2), appids, historical): tracked[key] = process_start(match.group(2))
    def reconcile():
        for key, started in list(tracked.items()):
            if not started or process_start(key[1]) != started: tracked.pop(key, None)
        if tracked and not module_loaded():
            if start_backend(): owns.touch()
        elif not tracked and owns.exists(): stop_backend(); owns.unlink(missing_ok=True)
    while not log.is_file() and not stopping: time.sleep(1)
    position = 0
    try:
        with log.open(errors="replace") as stream:
            for line in stream: handle(line, historical=True)
            position = stream.tell()
        reconcile()
    except OSError:
        pass
    while not stopping:
        try:
            with log.open(errors="replace") as stream:
                stream.seek(position); inode = os.fstat(stream.fileno()).st_ino
                while not stopping:
                    line = stream.readline()
                    if line: position = stream.tell(); handle(line); reconcile()
                    else:
                        current = log.stat()
                        if current.st_ino != inode or current.st_size < position: position = 0; break
                        reconcile(); time.sleep(.5)
        except OSError: time.sleep(1)
    if owns.exists(): stop_backend(); owns.unlink(missing_ok=True)


def backend(action, values):
    if action not in ACTIONS or action == "cpuid_test": raise BackendError("Unknown backend action")
    if ACTIONS[action] and os.geteuid() != 0: raise BackendError("Administrator privileges are required")
    if ACTIONS[action] and APP != SERVICE_APP: raise BackendError("Privileged actions require the verified installed backend")
    dispatch = {
        "inspect": inspect_backend, "install": install_backend, "start": start_backend,
        "stop": stop_backend, "update": update_backend, "uninstall": uninstall_backend,
        "bootloader": lambda: print(bootloader()), "list_games": list_games_backend,
        "configure_games": lambda: configure_games_backend(values), "disable_games": disable_games_backend,
        "disable_umip": lambda: change_umip(True), "enable_umip": lambda: change_umip(False),
        "disable_umip_entry": lambda: change_umip(True, values[0] if values else None),
        "enable_umip_entry": lambda: change_umip(False, values[0] if values else None),
        "reboot": lambda: run(["systemctl", "reboot"]),
    }
    dispatch[action]()


USER = os.environ.get("SUDO_USER") or getpass.getuser()
NAMES = {"bazzite": "Bazzite", "steamos": "SteamOS", "linux": "Linux"}
TITLES = {
    "install": "Installing the kernel module", "start": "Starting the module",
    "stop": "Stopping the module", "update": "Updating the module",
    "uninstall": "Removing the module", "disable_umip": "Updating boot options",
    "disable_umip_entry": "Updating boot options", "enable_umip": "Restoring boot options",
    "enable_umip_entry": "Restoring boot options", "configure_games": "Applying game selection",
    "disable_games": "Disabling automatic activation", "reboot": "Restarting the system",
}


class OperationWindow(Adw.Window):
    def __init__(self, parent, title):
        super().__init__(transient_for=parent, modal=True, title=title,
                         default_width=620, default_height=440)
        self.running = True
        toolbar = Adw.ToolbarView(); header = Adw.HeaderBar(show_end_title_buttons=False)
        self.done = Gtk.Button(label="Done", sensitive=False); self.done.connect("clicked", lambda *_: self.close())
        self.extra = Gtk.Button(visible=False); header.pack_end(self.done); header.pack_end(self.extra); toolbar.add_top_bar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=22, margin_bottom=18, margin_start=22, margin_end=22)
        top = Gtk.Box(spacing=12)
        self.spinner = Adw.Spinner(width_request=32, height_request=32); top.append(self.spinner)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.heading = Gtk.Label(label=title, xalign=0, css_classes=["title-2"])
        self.summary = Gtk.Label(label="This may take a few minutes. You can follow the details below.", xalign=0,
                                 wrap=True, css_classes=["dim-label"])
        labels.append(self.heading); labels.append(self.summary); top.append(labels); box.append(top)
        self.view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                 left_margin=12, right_margin=12, top_margin=10, bottom_margin=10)
        scroll = Gtk.ScrolledWindow(vexpand=True, css_classes=["output"]); scroll.set_child(self.view); box.append(scroll)
        toolbar.set_content(box); self.set_content(toolbar)
        self.connect("close-request", lambda *_: self.running)

    def append(self, text):
        buf = self.view.get_buffer(); buf.insert(buf.get_end_iter(), text)
        mark = buf.create_mark(None, buf.get_end_iter(), False); self.view.scroll_mark_onscreen(mark)

    def finish(self, success):
        self.running = False; self.spinner.set_visible(False); self.done.set_sensitive(True)
        self.heading.set_text("Completed" if success else "Something went wrong")
        self.summary.set_text("The operation completed successfully." if success else
                              "Review the output below, then try again.")
        self.done.add_css_class("suggested-action" if success else "destructive-action")

    def offer_reboot(self, callback):
        self.done.set_label("Later"); self.done.remove_css_class("suggested-action")
        self.extra.set_label("Restart now"); self.extra.set_visible(True); self.extra.add_css_class("suggested-action")
        self.extra.connect("clicked", lambda *_: (self.close(), callback()))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="dev.pareidolia.hvinstaller")
        self.state = parse_status("")
        self.probe_result = None
        self.probe_started = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider(); css.load_from_string("""
            .hero { padding: 24px; border-radius: 14px; }
            .status-orb { padding: 15px; border-radius: 999px; }
            .status-good { color: @success_color; background: alpha(@success_color, .14); }
            .status-warn { color: @warning_color; background: alpha(@warning_color, .14); }
            .status-bad { color: @error_color; background: alpha(@error_color, .14); }
            .output { border: 1px solid alpha(currentColor, .15); border-radius: 10px; }
            .section-note { font-size: .9em; }
        """)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                   Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if hasattr(self, "win"):
            self.win.present(); return
        self.win = Adw.ApplicationWindow(application=self, title="HV Setup",
                                         default_width=720, default_height=650)
        toolbar = Adw.ToolbarView(); header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="HV Setup", subtitle="CPUID Fault Emulation"))
        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh status")
        self.refresh_button.connect("clicked", lambda *_: self.refresh()); header.pack_end(self.refresh_button)
        toolbar.add_top_bar(header)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.loading_page(), "loading")
        self.stack.add_named(self.setup_page(), "setup")
        self.stack.add_named(self.dashboard_page(), "dashboard")
        self.toasts = Adw.ToastOverlay(child=self.stack); toolbar.set_content(self.toasts)
        self.win.set_content(toolbar); self.win.present(); self.refresh()
        GLib.timeout_add_seconds(5, self.periodic_refresh)

    def loading_page(self):
        return Adw.StatusPage(icon_name="content-loading-symbolic", title="Checking your system…",
                              description="Looking for the module and automatic game activation.")

    def setup_page(self):
        self.setup_status = Adw.StatusPage(icon_name="application-x-firmware-symbolic",
                                           title="Set up CPUID Fault Emulation")
        self.setup_description = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER,
                                           max_width_chars=56, css_classes=["dim-label"])
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.setup_umip = Gtk.Button(label="Configure boot options", visible=False)
        self.setup_umip.connect("clicked", self.confirm_umip); buttons.append(self.setup_umip)
        self.install_button = Gtk.Button(label="Install module", css_classes=["suggested-action", "pill"])
        self.install_button.connect("clicked", lambda *_: self.confirm_install()); buttons.append(self.install_button)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.append(self.setup_description); box.append(buttons); self.setup_status.set_child(box)
        return self.setup_status

    def dashboard_page(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20,
                          margin_top=24, margin_bottom=32, margin_start=24, margin_end=24)
        hero = Gtk.Box(spacing=18, css_classes=["card", "hero"])
        self.orb = Gtk.Box(css_classes=["status-orb"])
        self.module_icon = Gtk.Image(pixel_size=28); self.orb.append(self.module_icon); hero.append(self.orb)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.module_title = Gtk.Label(xalign=0, css_classes=["title-2"])
        self.module_subtitle = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        copy.append(self.module_title); copy.append(self.module_subtitle); hero.append(copy)
        self.module_button = Gtk.Button(valign=Gtk.Align.CENTER); self.module_button.connect("clicked", self.toggle_module)
        hero.append(self.module_button); content.append(hero)

        module = Adw.PreferencesGroup(title="Compatibility and setup")
        self.system_row = Adw.ActionRow(title="Running kernel")
        module.add(self.system_row)
        self.probe_row = Adw.ActionRow(title="CPUID faulting", subtitle="Checking compatibility…")
        self.probe_icon = Gtk.Image(icon_name="content-loading-symbolic", pixel_size=16)
        test = Gtk.Button(label="Test", valign=Gtk.Align.CENTER); test.connect("clicked", self.test_cpuid)
        self.probe_row.add_suffix(self.probe_icon); self.probe_row.add_suffix(test); module.add(self.probe_row)
        self.update_row = self.action_row("Kernel module", "Rebuild for the current kernel", "Update…", self.confirm_update)
        module.add(self.update_row)
        self.umip_row = Adw.ActionRow(title="UMIP boot option")
        self.umip_button = Gtk.Button(label="Configure…", valign=Gtk.Align.CENTER)
        self.umip_button.connect("clicked", self.toggle_umip); self.umip_row.add_suffix(self.umip_button); module.add(self.umip_row)
        content.append(module)

        games = Adw.PreferencesGroup(title="Automatic game activation",
                                     description="Run the module only while selected non-Steam shortcuts are active.")
        self.games_row = Adw.ActionRow(title="HV Games")
        self.games_disable = Gtk.Button(icon_name="media-playback-stop-symbolic", valign=Gtk.Align.CENTER,
                                        tooltip_text="Disable automatic activation")
        self.games_disable.connect("clicked", self.confirm_disable_games)
        configure = Gtk.Button(label="Choose games…", valign=Gtk.Align.CENTER)
        configure.connect("clicked", self.load_games)
        self.games_row.add_suffix(self.games_disable); self.games_row.add_suffix(configure); games.add(self.games_row)
        content.append(games)

        maintenance = Adw.PreferencesGroup(title="Maintenance")
        maintenance.add(self.action_row("Remove module", "Stop and uninstall CPUID Fault Emulation",
                                        "Remove…", self.confirm_uninstall, destructive=True))
        content.append(maintenance)
        clamp = Adw.Clamp(maximum_size=720, tightening_threshold=600); clamp.set_child(content)
        scroll = Gtk.ScrolledWindow(); scroll.set_child(clamp); return scroll

    @staticmethod
    def action_row(title, subtitle, label, callback, destructive=False):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        if destructive: button.add_css_class("destructive-action")
        button.connect("clicked", callback); row.add_suffix(button); return row

    def refresh(self):
        self.refresh_button.set_sensitive(False); self.stack.set_visible_child_name("loading")
        self.read("inspect", self.apply_status)

    def read(self, action, callback, values=()):
        def worker():
            result = subprocess.run(command(action, USER, values), text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            GLib.idle_add(callback, result.returncode, result.stdout)
        threading.Thread(target=worker, daemon=True).start()

    def apply_status(self, code, output):
        self.refresh_button.set_sensitive(True)
        if code:
            self.stack.set_visible_child_name("setup")
            self.setup_description.set_text(output.strip() or "Could not inspect the system.")
            self.toast("System check failed"); return
        self.state = parse_status(output); os_name = NAMES.get(self.state["os"], self.state["os"].title())
        if not self.state["installed"]:
            local = self.state["os"] in {"bazzite", "steamos"}
            detail = ("A kernel-matched module will be compiled in Podman. The build image uses about 1–2 GB."
                      if local else "Build tools and kernel headers will be installed, then the module will be managed with DKMS.")
            self.setup_status.set_title("Set up CPUID Fault Emulation")
            self.setup_status.set_icon_name("application-x-firmware-symbolic")
            self.install_button.set_label("Install module"); self.setup_umip.set_visible(False)
            self.setup_description.set_text(f"Detected {os_name}. {detail}\n\nAdministrator approval is required.")
            self.stack.set_visible_child_name("setup")
        else:
            self.update_dashboard(os_name); self.stack.set_visible_child_name("dashboard")
        if self.probe_result:
            self.apply_probe_result(*self.probe_result, show_dialog=False)
        elif not self.probe_started:
            self.test_cpuid(silent=True)

    def update_dashboard(self, os_name):
        if self.state["loaded"]:
            title, subtitle, icon, style = "Module is running", "CPUID fault emulation is active.", "media-playback-start-symbolic", "status-good"
            self.module_button.set_label("Stop"); self.module_button.set_css_classes([])
        elif not self.state["matching"]:
            title, subtitle, icon, style = "Update required", "Rebuild the module for the current kernel before starting.", "software-update-urgent-symbolic", "status-bad"
            self.module_button.set_label("Update…"); self.module_button.set_css_classes(["suggested-action"])
        else:
            title, subtitle, icon, style = "Ready when you are", "Installed and currently stopped.", "media-playback-pause-symbolic", "status-warn"
            self.module_button.set_label("Start"); self.module_button.set_css_classes(["suggested-action"])
        self.module_title.set_text(title); self.module_subtitle.set_text(f"{subtitle}  •  {os_name}")
        self.module_icon.set_from_icon_name(icon); self.orb.set_css_classes(["status-orb", style])
        self.system_row.set_subtitle(f"{os_name} • {self.state['kernel']}")
        disabled = self.state["umip"] == "disabled"
        configured = self.state["umip_arg"] == "present"
        self.umip_row.set_title("UMIP is disabled" if disabled else "UMIP is enabled")
        if configured:
            subtitle = "clearcpuid=514 is applied" if disabled else "clearcpuid=514 is applied. Restart required"
        else:
            subtitle = "clearcpuid=514 is not applied" if not disabled else "No clearcpuid override is configured"
        self.umip_row.set_subtitle(subtitle)
        self.umip_button.set_label("Restore…" if configured else "Disable…")
        local = self.state["os"] in {"bazzite", "steamos"}
        self.update_row.set_subtitle("Rebuild with the kernel-matched container" if local else "Rebuild and reinstall through DKMS")
        watcher = self.state["watcher"]; count = len(self.state["configured"])
        descriptions = {"running": f"Enabled and monitoring {count} selected shortcut(s)",
                        "enabled": f"Enabled but not running • {count} selected shortcut(s)",
                        "disabled": "Disabled. Choose shortcuts to enable it"}
        self.games_row.set_subtitle(descriptions[watcher]); self.games_disable.set_visible(watcher != "disabled")

    def periodic_refresh(self):
        if self.win.get_visible(): self.refresh_background()
        return GLib.SOURCE_CONTINUE

    def test_cpuid(self, *_args, silent=False):
        self.probe_started = True
        self.probe_row.set_subtitle("Running the isolated diagnostic…")
        self.read("cpuid_test", lambda code, output: self.apply_probe_result(code, output, show_dialog=not silent))

    def apply_probe_result(self, code, output, loaded_at_test=None, show_dialog=False):
        loaded_at_test = self.state["loaded"] if loaded_at_test is None else loaded_at_test
        self.probe_result = (code, output, loaded_at_test)
        title, successful_test, detail = probe_summary(code, loaded_at_test)
        self.probe_row.set_subtitle(f"{title}. {detail}")
        self.probe_icon.set_from_icon_name("object-select-symbolic" if successful_test else "dialog-warning-symbolic")
        native = code == 0 and not loaded_at_test
        if native and not self.state["installed"]:
            self.setup_status.set_title("Your CPU supports CPUID faulting")
            self.setup_status.set_icon_name("object-select-symbolic")
            self.setup_description.set_text("The emulation module is not required on this CPU. You may still need to disable UMIP for affected games.")
            self.setup_umip.set_visible(self.state["umip"] != "disabled")
            self.install_button.set_label("Install anyway")
        if show_dialog:
            view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                left_margin=10, right_margin=10, top_margin=8, bottom_margin=8)
            view.get_buffer().set_text(output.strip() or "No diagnostic output was produced.")
            scroll = Gtk.ScrolledWindow(min_content_height=170, max_content_height=300,
                                        propagate_natural_height=True, css_classes=["output"])
            scroll.set_child(view)
            dialog = Adw.AlertDialog(heading=title, body=detail, extra_child=scroll)
            dialog.add_response("close", "Close"); dialog.present(self.win)

    def toggle_module(self, _):
        if not self.state["matching"]: self.confirm_update()
        else: self.execute("stop" if self.state["loaded"] else "start")

    def confirm_install(self, *_):
        local = self.state["os"] in {"bazzite", "steamos"}
        body = ("This downloads/builds a 1–2 GB Podman image and compiles a module for your current kernel."
                if local else "This installs build tools and kernel headers, then builds and installs the module with DKMS.")
        self.confirm("Install CPUID Fault Emulation?", body, "Install", "install")

    def confirm_update(self, *_):
        detail = ("The build container will be updated and the local module rebuilt." if self.state["os"] in {"bazzite", "steamos"}
                  else "The source will be rebuilt and reinstalled through DKMS for the current kernel.")
        self.confirm("Rebuild for the current kernel?", detail, "Update", "update")

    def confirm_uninstall(self, *_):
        self.confirm("Remove CPUID Fault Emulation?", "The module will be stopped first. Automatic game activation will also be disabled.",
                     "Remove", "uninstall", destructive=True)

    def confirm_disable_games(self, *_):
        self.confirm("Disable automatic activation?", "Your selected games will be retained for next time.",
                     "Disable", "disable_games", destructive=True)

    def toggle_umip(self, *_):
        if self.state["umip_arg"] == "present": self.confirm_enable_umip()
        else: self.confirm_umip()

    def confirm_umip(self, *_):
        self.confirm("Disable UMIP?", "This applies clearcpuid=514 to your boot options. You must restart before it takes effect.",
                     "Apply", callback=lambda: self.choose_umip_target("disable_umip"))

    def confirm_enable_umip(self, *_):
        self.confirm("Restore UMIP?", "This removes clearcpuid=514 from your boot options. You must restart before it takes effect.",
                     "Restore", callback=lambda: self.choose_umip_target("enable_umip"))

    def confirm(self, heading, body, label, action=None, destructive=False, callback=None):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel"); dialog.add_response("accept", label)
        dialog.set_close_response("cancel"); dialog.set_default_response("accept")
        dialog.set_response_appearance("accept", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", lambda _, response: (callback() if callback else self.execute(action)) if response == "accept" else None)
        dialog.present(self.win)

    def choose_umip_target(self, action):
        self.read("bootloader", lambda code, output: self.show_umip_target(code, output, action))

    def show_umip_target(self, code, output, action):
        bootloader = output.strip(); entries = sorted(Path("/boot/loader/entries").glob("*.conf")) if bootloader == "systemd-boot" else []
        if not entries:
            self.execute(action); return
        chooser = Gtk.DropDown.new_from_strings([entry.name for entry in entries])
        applying = action == "disable_umip"
        verb = "receive" if applying else "remove"
        dialog = Adw.AlertDialog(heading="Choose a boot entry",
                                 body=f"Select the systemd-boot entry that should {verb} clearcpuid=514.", extra_child=chooser)
        dialog.add_response("cancel", "Cancel"); dialog.add_response("apply", "Apply" if applying else "Restore")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        entry_action = "disable_umip_entry" if applying else "enable_umip_entry"
        dialog.connect("response", lambda _, response: self.execute(entry_action, [str(entries[chooser.get_selected()])]) if response == "apply" else None)
        dialog.present(self.win)

    def load_games(self, *_):
        self.toast("Reading Steam shortcuts…"); self.read("list_games", self.show_games)

    def show_games(self, code, output):
        games = [line.split("\t", 1) for line in output.splitlines() if "\t" in line]
        if code or not games:
            dialog = Adw.AlertDialog(heading="No Steam shortcuts found",
                                     body=output.strip() or "Add a non-Steam shortcut in Steam, then try again.")
            dialog.add_response("close", "Close"); dialog.present(self.win); return
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        checks = []
        for appid, name in sorted(games, key=lambda game: game[1].casefold()):
            check = Gtk.CheckButton(label=name, active=appid in self.state["configured"], margin_top=8,
                                    margin_bottom=8, margin_start=12, margin_end=12)
            check.set_tooltip_text(f"Steam shortcut AppID {appid}"); listing.append(check); checks.append((appid, check))
        scroll = Gtk.ScrolledWindow(min_content_height=220, max_content_height=360, propagate_natural_height=True)
        scroll.set_child(listing)
        dialog = Adw.AlertDialog(heading="Choose HV Games",
                                 body="Apply the shortcuts that should use the module. Clear every selection to disable automatic activation.", extra_child=scroll)
        dialog.add_response("cancel", "Cancel"); dialog.add_response("apply", "Apply")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        def apply_selection():
            action, values = game_selection_action(appid for appid, check in checks if check.get_active())
            self.execute(action, values)
        dialog.connect("response", lambda _, response: apply_selection() if response == "apply" else None)
        dialog.present(self.win)

    def execute(self, action, values=()):
        operation = OperationWindow(self.win, TITLES[action]); operation.present()
        def worker():
            output = []
            try:
                if ACTIONS[action]: install_backend_copy()
                process = subprocess.Popen(command(action, USER, values), text=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
                for line in process.stdout:
                    output.append(line); GLib.idle_add(operation.append, line)
                code = process.wait()
            except Exception as error:
                output.append(f"{error}\n"); GLib.idle_add(operation.append, output[-1]); code = 1
            GLib.idle_add(self.action_finished, action, code, "".join(output), operation)
        threading.Thread(target=worker, daemon=True).start()

    def action_finished(self, action, code, output, operation):
        operation.finish(code == 0)
        if code == 0:
            if "umip" in action:
                message = "Restart required for the boot option to take effect"
                operation.offer_reboot(lambda: self.execute("reboot"))
            else:
                message = "Changes applied successfully"
            if action in {"install", "start", "stop", "update", "uninstall"}:
                self.probe_result = None; self.probe_started = False
            self.toast(message); self.refresh_background()
        else:
            self.toast("Operation failed. Review the details")

    def refresh_background(self):
        self.read("inspect", lambda code, output: self.apply_status(code, output))

    def toast(self, message):
        self.toasts.add_toast(Adw.Toast(title=message, timeout=3))


if __name__ == "__main__":
    try:
        if "--cpuid-probe" in sys.argv:
            raise SystemExit(cpuid_probe())
        if len(sys.argv) >= 3 and sys.argv[1] == "--backend":
            backend(sys.argv[2], sys.argv[3:]); raise SystemExit(0)
        if len(sys.argv) == 2 and sys.argv[1] == "--watch":
            if os.geteuid() != 0: raise BackendError("The watcher requires administrator privileges")
            watch_games(); raise SystemExit(0)
        raise SystemExit(App().run(sys.argv))
    except BackendError as error:
        print(error, file=sys.stderr); raise SystemExit(1)
    except Exception:
        traceback.print_exc(); raise SystemExit(7)
