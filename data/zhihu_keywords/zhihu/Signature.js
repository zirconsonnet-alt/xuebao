h = {
  "zk": [
    1170614578,
    1024848638,
    1413669199,
    -343334464,
    -766094290,
    -1373058082,
    -143119608,
    -297228157,
    1933479194,
    -971186181,
    -406453910,
    460404854,
    -547427574,
    -1891326262,
    -1679095901,
    2119585428,
    -2029270069,
    2035090028,
    -1521520070,
    -5587175,
    -77751101,
    -2094365853,
    -1243052806,
    1579901135,
    1321810770,
    456816404,
    -1391643889,
    -229302305,
    330002838,
    -788960546,
    363569021,
    -1947871109
  ],
  "zb": [
    20,
    223,
    245,
    7,
    248,
    2,
    194,
    209,
    87,
    6,
    227,
    253,
    240,
    128,
    222,
    91,
    237,
    9,
    125,
    157,
    230,
    93,
    252,
    205,
    90,
    79,
    144,
    199,
    159,
    197,
    186,
    167,
    39,
    37,
    156,
    198,
    38,
    42,
    43,
    168,
    217,
    153,
    15,
    103,
    80,
    189,
    71,
    191,
    97,
    84,
    247,
    95,
    36,
    69,
    14,
    35,
    12,
    171,
    28,
    114,
    178,
    148,
    86,
    182,
    32,
    83,
    158,
    109,
    22,
    255,
    94,
    238,
    151,
    85,
    77,
    124,
    254,
    18,
    4,
    26,
    123,
    176,
    232,
    193,
    131,
    172,
    143,
    142,
    150,
    30,
    10,
    146,
    162,
    62,
    224,
    218,
    196,
    229,
    1,
    192,
    213,
    27,
    110,
    56,
    231,
    180,
    138,
    107,
    242,
    187,
    54,
    120,
    19,
    44,
    117,
    228,
    215,
    203,
    53,
    239,
    251,
    127,
    81,
    11,
    133,
    96,
    204,
    132,
    41,
    115,
    73,
    55,
    249,
    147,
    102,
    48,
    122,
    145,
    106,
    118,
    74,
    190,
    29,
    16,
    174,
    5,
    177,
    129,
    63,
    113,
    99,
    31,
    161,
    76,
    246,
    34,
    211,
    13,
    60,
    68,
    207,
    160,
    65,
    111,
    82,
    165,
    67,
    169,
    225,
    57,
    112,
    244,
    155,
    51,
    236,
    200,
    233,
    58,
    61,
    47,
    100,
    137,
    185,
    64,
    17,
    70,
    234,
    163,
    219,
    108,
    170,
    166,
    59,
    149,
    52,
    105,
    24,
    212,
    78,
    173,
    45,
    0,
    116,
    226,
    119,
    136,
    206,
    135,
    175,
    195,
    25,
    92,
    121,
    208,
    126,
    139,
    3,
    75,
    141,
    21,
    130,
    98,
    241,
    40,
    154,
    66,
    184,
    49,
    181,
    46,
    243,
    88,
    101,
    183,
    8,
    23,
    72,
    188,
    104,
    179,
    210,
    134,
    250,
    201,
    164,
    89,
    216,
    202,
    220,
    50,
    221,
    152,
    140,
    33,
    235,
    214
  ],
  "zm": [
    120,
    50,
    98,
    101,
    99,
    98,
    119,
    100,
    103,
    107,
    99,
    119,
    97,
    99,
    110,
    111
  ]
}


function o (e) {
  return (o = "function" == typeof Symbol && "symbol" == typeof Symbol.A ? function (e) {
    return typeof e
  }
    : function (e) {
      return e && "function" == typeof Symbol && e.constructor === Symbol && e !== Symbol.prototype ? "symbol" : typeof e
    }
  )(e)
}
function x (e) {
  return C(e) || s(e) || t()
}
function C (e) {
  if (Array.isArray(e)) {
    for (var t = 0, n = new Array(e.length); t < e.length; t++)
      n[t] = e[t];
    return n
  }
}
function s (e) {
  if (Symbol.A in Object(e) || "[object Arguments]" === Object.prototype.toString.call(e))
    return Array.from(e)
}
function t () {
  throw new TypeError("Invalid attempt to spread non-iterable instance")
}

var A = "3.0", S = "undefined" != typeof window ? window : {}, h;
function i (e, t, n) {
  t[n] = 255 & e >>> 24,
    t[n + 1] = 255 & e >>> 16,
    t[n + 2] = 255 & e >>> 8,
    t[n + 3] = 255 & e
}
function B (e, t) {
  return (255 & e[t]) << 24 | (255 & e[t + 1]) << 16 | (255 & e[t + 2]) << 8 | 255 & e[t + 3]
}
function Q (e, t) {
  return (4294967295 & e) << t | e >>> 32 - t
}
function G (e) {
  var t = new Array(4)
    , n = new Array(4);
  i(e, t, 0),
    n[0] = h.zb[255 & t[0]],
    n[1] = h.zb[255 & t[1]],
    n[2] = h.zb[255 & t[2]],
    n[3] = h.zb[255 & t[3]];
  var r = B(n, 0);
  return r ^ Q(r, 2) ^ Q(r, 10) ^ Q(r, 18) ^ Q(r, 24)
}
var __g = {
  x: function (e, t) {
    for (var n = [], r = e.length, i = 0; 0 < r; r -= 16) {
      for (var o = e.slice(16 * i, 16 * (i + 1)), a = new Array(16), c = 0; c < 16; c++)
        a[c] = o[c] ^ t[c];
      t = __g.r(a),
        n = n.concat(t),
        i++
    }
    return n
  },
  r: function (e) {
    var t = new Array(16)
      , n = new Array(36);
    n[0] = B(e, 0),
      n[1] = B(e, 4),
      n[2] = B(e, 8),
      n[3] = B(e, 12);
    for (var r = 0; r < 32; r++) {
      var o = G(n[r + 1] ^ n[r + 2] ^ n[r + 3] ^ h.zk[r]);
      n[r + 4] = n[r] ^ o
    }
    return i(n[35], t, 0),
      i(n[34], t, 4),
      i(n[33], t, 8),
      i(n[32], t, 12),
      t
  }
};


// md5函数

const md51 = (val) => {
  var hexcase = 0;  /* hex output format. 0 - lowercase; 1 - uppercase       */
  var chrsz = 8;  /* bits per input character. 8 - ASCII; 16 - Unicode     */

  function hex_md5 (s) {
    return binl2hex(core_md5(str2binl(s), s.length * chrsz));
  }

  /*
   * Convert an array of little-endian words to a hex string.
   */
  function binl2hex (binarray) {
    var hex_tab = hexcase ? "0123456789ABCDEF" : "0123456789abcdef";
    var str = "";
    for (var i = 0; i < binarray.length * 4; i++) {
      str += hex_tab.charAt((binarray[i >> 2] >> ((i % 4) * 8 + 4)) & 0xF) +
        hex_tab.charAt((binarray[i >> 2] >> ((i % 4) * 8)) & 0xF);
    }
    return str;
  }

  function core_md5 (x, len) {
    /* append padding */
    x[len >> 5] |= 0x80 << ((len) % 32);
    x[(((len + 64) >>> 9) << 4) + 14] = len;

    var a = 1732584193;
    var b = -271733879;
    var c = -1732584194;
    var d = 271733878;

    for (var i = 0; i < x.length; i += 16) {
      var olda = a;
      var oldb = b;
      var oldc = c;
      var oldd = d;

      a = md5_ff(a, b, c, d, x[i + 0], 7, -680876936);
      d = md5_ff(d, a, b, c, x[i + 1], 12, -389564586);
      c = md5_ff(c, d, a, b, x[i + 2], 17, 606105819);
      b = md5_ff(b, c, d, a, x[i + 3], 22, -1044525330);
      a = md5_ff(a, b, c, d, x[i + 4], 7, -176418897);
      d = md5_ff(d, a, b, c, x[i + 5], 12, 1200080426);
      c = md5_ff(c, d, a, b, x[i + 6], 17, -1473231341);
      b = md5_ff(b, c, d, a, x[i + 7], 22, -45705983);
      a = md5_ff(a, b, c, d, x[i + 8], 7, 1770035416);
      d = md5_ff(d, a, b, c, x[i + 9], 12, -1958414417);
      c = md5_ff(c, d, a, b, x[i + 10], 17, -42063);
      b = md5_ff(b, c, d, a, x[i + 11], 22, -1990404162);
      a = md5_ff(a, b, c, d, x[i + 12], 7, 1804603682);
      d = md5_ff(d, a, b, c, x[i + 13], 12, -40341101);
      c = md5_ff(c, d, a, b, x[i + 14], 17, -1502002290);
      b = md5_ff(b, c, d, a, x[i + 15], 22, 1236535329);

      a = md5_gg(a, b, c, d, x[i + 1], 5, -165796510);
      d = md5_gg(d, a, b, c, x[i + 6], 9, -1069501632);
      c = md5_gg(c, d, a, b, x[i + 11], 14, 643717713);
      b = md5_gg(b, c, d, a, x[i + 0], 20, -373897302);
      a = md5_gg(a, b, c, d, x[i + 5], 5, -701558691);
      d = md5_gg(d, a, b, c, x[i + 10], 9, 38016083);
      c = md5_gg(c, d, a, b, x[i + 15], 14, -660478335);
      b = md5_gg(b, c, d, a, x[i + 4], 20, -405537848);
      a = md5_gg(a, b, c, d, x[i + 9], 5, 568446438);
      d = md5_gg(d, a, b, c, x[i + 14], 9, -1019803690);
      c = md5_gg(c, d, a, b, x[i + 3], 14, -187363961);
      b = md5_gg(b, c, d, a, x[i + 8], 20, 1163531501);
      a = md5_gg(a, b, c, d, x[i + 13], 5, -1444681467);
      d = md5_gg(d, a, b, c, x[i + 2], 9, -51403784);
      c = md5_gg(c, d, a, b, x[i + 7], 14, 1735328473);
      b = md5_gg(b, c, d, a, x[i + 12], 20, -1926607734);

      a = md5_hh(a, b, c, d, x[i + 5], 4, -378558);
      d = md5_hh(d, a, b, c, x[i + 8], 11, -2022574463);
      c = md5_hh(c, d, a, b, x[i + 11], 16, 1839030562);
      b = md5_hh(b, c, d, a, x[i + 14], 23, -35309556);
      a = md5_hh(a, b, c, d, x[i + 1], 4, -1530992060);
      d = md5_hh(d, a, b, c, x[i + 4], 11, 1272893353);
      c = md5_hh(c, d, a, b, x[i + 7], 16, -155497632);
      b = md5_hh(b, c, d, a, x[i + 10], 23, -1094730640);
      a = md5_hh(a, b, c, d, x[i + 13], 4, 681279174);
      d = md5_hh(d, a, b, c, x[i + 0], 11, -358537222);
      c = md5_hh(c, d, a, b, x[i + 3], 16, -722521979);
      b = md5_hh(b, c, d, a, x[i + 6], 23, 76029189);
      a = md5_hh(a, b, c, d, x[i + 9], 4, -640364487);
      d = md5_hh(d, a, b, c, x[i + 12], 11, -421815835);
      c = md5_hh(c, d, a, b, x[i + 15], 16, 530742520);
      b = md5_hh(b, c, d, a, x[i + 2], 23, -995338651);

      a = md5_ii(a, b, c, d, x[i + 0], 6, -198630844);
      d = md5_ii(d, a, b, c, x[i + 7], 10, 1126891415);
      c = md5_ii(c, d, a, b, x[i + 14], 15, -1416354905);
      b = md5_ii(b, c, d, a, x[i + 5], 21, -57434055);
      a = md5_ii(a, b, c, d, x[i + 12], 6, 1700485571);
      d = md5_ii(d, a, b, c, x[i + 3], 10, -1894986606);
      c = md5_ii(c, d, a, b, x[i + 10], 15, -1051523);
      b = md5_ii(b, c, d, a, x[i + 1], 21, -2054922799);
      a = md5_ii(a, b, c, d, x[i + 8], 6, 1873313359);
      d = md5_ii(d, a, b, c, x[i + 15], 10, -30611744);
      c = md5_ii(c, d, a, b, x[i + 6], 15, -1560198380);
      b = md5_ii(b, c, d, a, x[i + 13], 21, 1309151649);
      a = md5_ii(a, b, c, d, x[i + 4], 6, -145523070);
      d = md5_ii(d, a, b, c, x[i + 11], 10, -1120210379);
      c = md5_ii(c, d, a, b, x[i + 2], 15, 718787259);
      b = md5_ii(b, c, d, a, x[i + 9], 21, -343485551);

      a = safe_add(a, olda);
      b = safe_add(b, oldb);
      c = safe_add(c, oldc);
      d = safe_add(d, oldd);
    }
    return Array(a, b, c, d);

  }

  /*
   * These functions implement the four basic operations the algorithm uses.
   */
  function md5_cmn (q, a, b, x, s, t) {
    return safe_add(bit_rol(safe_add(safe_add(a, q), safe_add(x, t)), s), b);
  }

  function bit_rol (num, cnt) {
    return (num << cnt) | (num >>> (32 - cnt));
  }

  function md5_ff (a, b, c, d, x, s, t) {
    return md5_cmn((b & c) | ((~b) & d), a, b, x, s, t);
  }

  function md5_gg (a, b, c, d, x, s, t) {
    return md5_cmn((b & d) | (c & (~d)), a, b, x, s, t);
  }

  function md5_hh (a, b, c, d, x, s, t) {
    return md5_cmn(b ^ c ^ d, a, b, x, s, t);
  }

  function md5_ii (a, b, c, d, x, s, t) {
    return md5_cmn(c ^ (b | (~d)), a, b, x, s, t);
  }

  function safe_add (x, y) {
    var lsw = (x & 0xFFFF) + (y & 0xFFFF);
    var msw = (x >> 16) + (y >> 16) + (lsw >> 16);
    return (msw << 16) | (lsw & 0xFFFF);
  }

  /*
   * Convert a string to an array of little-endian words
   * If chrsz is ASCII, characters >255 have their hi-byte silently ignored.
   */
  function str2binl (str) {
    var bin = Array();
    var mask = (1 << chrsz) - 1;
    for (var i = 0; i < str.length * chrsz; i += chrsz)
      bin[i >> 5] |= (str.charCodeAt(i / chrsz) & mask) << (i % 32);
    return bin;
  }
  return hex_md5(val)

}



// 10963689 = > BsdB
function encode (param) {
  var salt = '6fpLRqJO8M/c3jnYxFkUVC4ZIG12SiH=5v0mXDazWBTsuw7QetbKdoPyAl+hN9rgE'
  let ret = ''
  // 这里对应点在 case 57
  for (x of [0, 6, 12, 18]) {
    let a = param >>> x
    let b = a & 63
    let c = salt.charAt(b)
    ret = ret + c
  }
  // console.log(ret)
  return ret
}


//////////////////////////////////////

function get_md5_charCodeAt_arr (md5_str) {

  // 第一步：把md5字符串变成32位的数组
  var md5_charCodeAt_arr = []
  for (let i = 0; i < md5_str.length; i++) {
    md5_charCodeAt_arr.push(md5_str.charCodeAt(i))
  }

  // 第二步：用随机数与127进行计算，得到一个浮点数，向下取整
  // const temp_random = 0.08636862211354912 * 127;
  const temp_random = (Math.random()) * 127;
  //通过Math.floor向下取整
  const temp_random_int = Math.floor(temp_random); // 10


  //第三步：用上面计算到的39插入到数组头部

  // 向数组开头添加一个新的元素 0
  md5_charCodeAt_arr.unshift(0)
  // 向数组开头添加一个新的元素 17,也就是上面计算出来的 可随机可固定
  md5_charCodeAt_arr.unshift(temp_random_int)

  // 到此数组长度是32+2=34

  // 第四步：往数组中放入14个14
  for (let i = 0; i < 14; i++) {
    md5_charCodeAt_arr.push(14)
  }
  return md5_charCodeAt_arr;
}

function get_new_md5_charCodeAt_arr_16 (md5_arr) {

  // 第五步：截取数组前16位
  var md5_charCodeAt_arr_16 = md5_arr.slice(0, 16)
  // md5_charCodeAt_arr_16 -> 10, 0, 102, 49, 102, 97, 57, 54, 99, 55, 49, 52, 99, 54, 55, 53


  // 第六步：将上面的16位数组转化成新的16位数组

  // 固定值
  var charCodeAt_arr_1 = [48, 53, 57, 48, 53, 51, 102, 55, 100, 49, 53, 101, 48, 49, 100, 55];

  var new_md5_charCodeAt_arr_16 = [];
  for (var key in md5_charCodeAt_arr_16) {
    new_md5_charCodeAt_arr_16.push(md5_charCodeAt_arr_16[key] ^ charCodeAt_arr_1[key] ^ 42);
  }
  // 因为是16位的数组，每个值都需要计算，所以相当于是分了16组，每组计算的结果都放入了一个新的数组中
  // new_md5_charCodeAt_arr_16 -> 16, 31, 117, 43, 121, 120, 117, 43, 45, 44, 46, 123, 121, 45, 121, 40

  return new_md5_charCodeAt_arr_16
}


function get_result_48_arr (md5_arr_16, md5_arr) {


  // 我们给上面的结果定义一个变量不然下面容易看的人头晕
  // 283 - 310 md5_charCodeAt_arr
  // 311 - 393 md5_arr_16
  // 调用 __g.r 方法
  var __g_r_res = __g.r(md5_arr_16)


  // 第七步：获取16-48之间的数
  //取md5_charCodeAt_arr中的16-48位，
  var md5_charCodeAt_arr2 = md5_arr.slice(16, 48);
  // 并与前面新16位数组重新生成新32位数组
  var __g_x_res = __g.x(md5_charCodeAt_arr2, __g_r_res);
  // 拿到结果 下面会用这个长度48的数组进行大量的运算 这里不就是我们需要的那个数组
  var result_48_arr = __g_r_res.concat(__g_x_res)

  return result_48_arr;
}


function get_signature (url) {

  const md5_str = md51(url);

  const md5_arr = get_md5_charCodeAt_arr(md5_str);
  const md5_arr_16 = get_new_md5_charCodeAt_arr_16(md5_arr);
  const result_48_arr = get_result_48_arr(md5_arr_16, md5_arr);
  const len = result_48_arr.length;

  var str = '2.0_';

  for (let index = 0; index < len; index = index + 3) {
    var i = index;
    var pop = result_48_arr.pop();
    var c_3_1 = i % 4;
    var c_3_2 = 8 * i;
    var c_3_3 = 58 >>> c_3_2;
    var c_3_4 = c_3_3 & 255;
    var c_3_5 = pop ^ c_3_4

    var a = c_3_5 // 这个值要参与运算 先保留起来


    i = index + 1;
    var pop = result_48_arr.pop();
    c_3_1 = i % 4;
    c_3_2 = 8 * i;
    c_3_3 = 58 >>> c_3_2;
    c_3_4 = c_3_3 & 255;
    c_3_5 = pop ^ c_3_4
    var b1 = c_3_5 << 8 // 74 << 8 -- > 18944

    var a1 = a | b1 // 233 | 18944 -- > 19177



    i = index + 2;
    var pop = result_48_arr.pop()
    c_3_1 = i % 4;
    c_3_2 = 8 * i;
    c_3_3 = 58 >>> c_3_2;
    c_3_4 = c_3_3 & 255;
    c_3_5 = pop ^ c_3_4


    var c = c_3_5 << 16 // 10944512
    var d = a1 | c; // 10963689
    str += encode(d)
  }

  return str;
}


// const test_url = '101_3_3.0+/api/v4/search_v3?gk_version=gz-gaokao&t=general&q=123&correction=1&offset=0&limit=20&filter_fields=&lc_idx=0&show_all_topics=0&search_source=Normal+ALBX-7xhdRWPTm7D3utOkTyjN7VQD-hni8E=|1661434611+3_2.0aR_sn77yn6O92wOB8hPZnQr0EMYxc4f18wNBUgpTQ6nxERFZsRY0-4Lm-h3_tufIwJS8gcxTgJS_AuPZNcXCTwxI78YxEM20s4PGDwN8gGcYAupMWufIoLVqr4gxrRPOI0cY7HL8qun9g93mFukyigcmebS_FwOYPRP0E4rZUrN9DDom3hnynAUMnAVPF_PhaueTFe99YDgKeDoYRUY964pMSRV9egH9sTcGCbVfq93Kh9oY1w38whefeLFpAheTV7YKVbV8jBx_k731AuomLUV_YwpVwqeqYH3KOcxmqwY_ADe1KceGHv98SLLsJgHGPcOKJcVMYB3VTCF1vuVMgUVC_JXxNcLLUBxG1G7m0wFm2LH_4G3CCg_zQ0LsYJH10UNqiuH_egHsYCeL8CVYbcuyDDxswuo8mMx1QwLGhGVfe0cf-Ug0Brg1rgS9YCVKMCp9c0XOiwSY9CHBUutCFJoYnbXMbixY10eVQ7OC3Bes'

// const res = get_signature(test_url);
// console.log(res);

// 2.0_zaYQi6ttd68CLg5848IOcobCxz2Gpv0SiTlImrO71=m0UKkoAdQdKs6U3AdI2V9h
