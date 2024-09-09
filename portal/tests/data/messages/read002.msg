From test001@test.ch  Mon Sep  2 19:14:39 2024
Return-Path: <test001@test.ch>
X-Original-To: app@portal.pmscienceprizes.org.nz
Delivered-To: app@portal.pmscienceprizes.org.nz
Received: from ZR1P278CU001.outbound.protection.outlook.com (mail-switzerlandnorthazon11022099.outbound.protection.outlook.com [40.107.168.99])
	by portal.pmscienceprizes.org.nz (Postfix) with ESMTPS id 825D9FAFBE
	for <app@portal.pmscienceprizes.org.nz>; Mon,  2 Sep 2024 19:14:39 +1200 (NZST)
ARC-Seal: i=1; a=rsa-sha256; s=arcselector10001; d=microsoft.com; cv=none;
 b=fdnt/ON3Y1pO8r8dAVcTn6qme5gHLl6MgU4Rhr6EmVN8qiIZ2Bu8KiR5Pxl5S3pQlYmZ48mQyOXY7PEGb2OW8UyFV/TC0mx7c3mxdh6GoEEpcV8iE2a9LkOpMTgw3cPVxLQL37lZazE7HSl71KHnTtS3NBJm09VJCHt7QYpoatqFR926TXvoYaMVLQsiKG3M8XzHluo6/opNvuzVceVlPV+UC7pnLo+et9jcQhsOuU9x9TpAoCzDuj/pEUtL9GMc1LyYqtHdW1NofRLi0NtZ6/bNyVrp4UnwqALSbllzKU+dZTzUTY6CxfZJurxrtHgjSpH4GOm5VQ/YciPsc5WJWA==
ARC-Message-Signature: i=1; a=rsa-sha256; c=relaxed/relaxed; d=microsoft.com;
 s=arcselector10001;
 h=From:Date:Subject:Message-ID:Content-Type:MIME-Version:X-MS-Exchange-AntiSpam-MessageData-ChunkCount:X-MS-Exchange-AntiSpam-MessageData-0:X-MS-Exchange-AntiSpam-MessageData-1;
 bh=COL7nyqyEvN6x8gQpj6mx7lNR7pww6nK5MasvSL2elQ=;
 b=dxlIP383Uwz9GUrQauR3ZLwaC5hRwg9NC3AtAIK7PP9B8x1EqL/Ozs1/RmB+q2D8grNOvLFpdoQtS3yz+9YAIgMRlbWWbPuQErTXtFPfR5GtQCuzlCEzneJa5FBLhcrVd9fmVmWPU+YhEjPI9FNlNUdFob0+TdOQ9X0twGc0Y7quJSUWeJ48On6e842hK/avcC3gmQfdTjb8gRwFR6uVlrygAN4sO/4hqCiGO3Rc1QWd8NQmPCJTr0bZsteHyoCF6AbeP0wDhaWWfR7wroDxopaG0jKoxDRG+RjxAIEglMJg5BVowlvpFeVgP6eMV8PVD9E6jwxCmAVF0Y5VQwMQew==
ARC-Authentication-Results: i=1; mx.microsoft.com 1; spf=pass
 smtp.mailfrom=uzh.ch; dmarc=pass action=none header.from=uzh.ch; dkim=pass
 header.d=uzh.ch; arc=none
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed; d=uzh.ch; s=selector1;
 h=From:Date:Subject:Message-ID:Content-Type:MIME-Version:X-MS-Exchange-SenderADCheck;
 bh=COL7nyqyEvN6x8gQpj6mx7lNR7pww6nK5MasvSL2elQ=;
 b=szKgbVIYz+5YfxHCQMbEBfaKY1XpHqxFGGgDrCTGt7THUV4AK8RsuLMvv7YpY/hYV1yia49hNdMUC87piIKGiJ/5fw+TYUVGWmivPm0ackRfzHUJqDqGAOdhoZb9qo4q70XEsacN1vKxJ5Oj1vbzQ2PpakMD6ub5NL1dbZDA0QVZR9tIyqz/Ms9qxQ2sLVl7Dhn7Puow4nOL19e+QKWXkHKCnivm1v73eG0RXGBuNM+T5SG7/ZW7kq0oh4DnUeQrMCNKvQRllp1QW9udBCw1xkDWvsnZQkUk5cKQRPyEeFDhOajAZfbvzGJRC2OalGQ37lBM8/epYEbtPBKyv4fJdw==
Received: from ZRAP278MB0737.CHEP278.PROD.OUTLOOK.COM (2603:10a6:910:49::8) by
 ZRAP278MB0898.CHEP278.PROD.OUTLOOK.COM (2603:10a6:910:49::6) with Microsoft
 SMTP Server (version=TLS1_2, cipher=TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384) id
 15.20.7918.24; Mon, 2 Sep 2024 07:14:27 +0000
Received: from ZRAP278MB0737.CHEP278.PROD.OUTLOOK.COM
 ([fe80::ee1b:d34e:5701:445f]) by ZRAP278MB0737.CHEP278.PROD.OUTLOOK.COM
 ([fe80::ee1b:d34e:5701:445f%3]) with mapi id 15.20.7918.024; Mon, 2 Sep 2024
 07:14:26 +0000
From: TESTER 002 <test001@test.ch>
To: "app@portal.pmscienceprizes.org.nz" <app@portal.pmscienceprizes.org.nz>
Subject: Read: [Prime Minister's Science Prizes] You are invited as a referee
 for a Prime Minister's Science Prizes application
Thread-Topic: [Prime Minister's Science Prizes] You are invited as a referee
 for a Prime Minister's Science Prizes application
Thread-Index: AQHa/Ow7dahhPWmMmE61892I+seX/g==
Date: Mon, 2 Sep 2024 07:14:26 +0000
Message-ID: <7e14074375084f58863dd9c157223bb0@uzh.ch>
Accept-Language: de-DE, en-US
Content-Language: de-DE
X-MS-Has-Attach:
X-MS-TNEF-Correlator:
authentication-results: dkim=none (message not signed)
 header.d=none;dmarc=none action=none header.from=uzh.ch;
x-ms-publictraffictype: Email
x-ms-traffictypediagnostic: ZRAP278MB0737:EE_|ZRAP278MB0898:EE_
x-ms-office365-filtering-correlation-id: 5a4b4916-8b11-4299-6212-08dccb1ee13a
x-ms-exchange-senderadcheck: 1
x-ms-exchange-antispam-relay: 0
x-microsoft-antispam: BCL:0;ARA:13230040|376014|1800799024|366016;
x-microsoft-antispam-message-info:
 =?us-ascii?Q?/RZ7cLPUqE6/dQs0hTeMCdYOkCBBzpOGK/h/eJ0W+/bV4+E44v4edpBhM25q?=
 =?us-ascii?Q?WexUm0p3CEdi/VLiAF0eAuJL73QV84NuEMxAyEnKg+LRRzj+jFgu2RBdtbBv?=
 =?us-ascii?Q?Vsf+qMo0SoreMDJBkZZcx9An0sL5ejEOItisK/0dmNcsH5zHfpzaqDAQ+Y3f?=
 =?us-ascii?Q?p//ZJ5FYH8nCQ+ADNNYZDUADCCX1JqwjSB1Wdhw9lGcBb3T6PYxUU+2Hn4n0?=
 =?us-ascii?Q?bYZoSOQtOiY0x8Yi906KU+eBDTiDq30OuaXOlOuFKWFu59HzCpSHfCLXA/mk?=
 =?us-ascii?Q?A5S56mhJSXWImZCcqsRkSHqXnbpWySf9NweQgx6tKnjL9B6jCFv7bxi8Vz86?=
 =?us-ascii?Q?5adzUWClipFto2zjIl8oWC9zYBlvOhPQDzy1pwbcIEGaOs+fi+6GvasFIV7t?=
 =?us-ascii?Q?WMqoWCr9fUqHhAextDRtAughZh94gXxVVHbe1YUs0VbYbT9uoFlP4s7nXNzj?=
 =?us-ascii?Q?pUQAd1M5QcUjgnkjxEJNwy95OyUU43NmgH7fbBlrJn357+WW2yIZIBVIsBEK?=
 =?us-ascii?Q?8o4UWVxA7bwaTMSG4cMevLDRwd9guTjKt7icq3zoTFySVtLc4E+Yi+xPaFwt?=
 =?us-ascii?Q?uHCvt5cj6a3ICtMQ1ayvd8x9me8Oi2TAViALd/AkQ2fdgwAFQ6YehVRczwrE?=
 =?us-ascii?Q?+j1Tl85c64bEMfbj25QRCm8S6n6vHAb7CAuEBjYo5wMgn/Uq/Ra3Gpb36MRD?=
 =?us-ascii?Q?oaTwigddqcQk9rbzq3l63z/+jxJpmdXDBgrSokA5aIh7BQx5/ZpfAHW2O439?=
 =?us-ascii?Q?BMnoKEP1H1e9+gX3kM9AXM9uUZ3I3CIJqHdwip+ETapSX+32Xb+ru5emTr9x?=
 =?us-ascii?Q?Z322vX6CCOdzlDmPZT4pZTBThfaMhmk3tNYAt/DQXMxgoSt2foF84hEzupFW?=
 =?us-ascii?Q?Egdckc13rh8CDwU3pkXwWa+NwVX21adIxaSMzC/IE3bL+Bbt0zUS3D79f/q6?=
 =?us-ascii?Q?fu44E7aeNIIQ49cUIk1LM3zFRV0h4dZ9fP/SJOxyl6ZsZoG32y3S3p+E36+w?=
 =?us-ascii?Q?xeQSZBn9MoTdUGrqv0nGAfQ2DVpllMGztWlO5tUZAMN8mwUJeSSTGSYL2aG3?=
 =?us-ascii?Q?Wgm/3h1IDRqx0FZCsZQ2VpdpB+YhuA=3D=3D?=
x-forefront-antispam-report:
 CIP:255.255.255.255;CTRY:;LANG:en;SCL:1;SRV:;IPV:NLI;SFV:NSPM;H:ZRAP278MB0737.CHEP278.PROD.OUTLOOK.COM;PTR:;CAT:NONE;SFS:(13230040)(376014)(1800799024)(366016);DIR:OUT;SFP:1102;
x-ms-exchange-antispam-messagedata-chunkcount: 1
x-ms-exchange-antispam-messagedata-0:
 =?us-ascii?Q?D8T4ehdT9U+zFfUokKwY/qL3XN/OHJ3dJcVu8ujTBuDtoD2+ga+Iy5HKzm37?=
 =?us-ascii?Q?wkIKojVcSRbnROweAfBr6PJpdJmfo1NvkIkvDEn8ZjdcEXzrYa9nBtDPS9TG?=
 =?us-ascii?Q?fk7SvUXZVO8LNHeHiJx0VgQww1r+LEG7Nr3EsHATWu7hs4QJc5FaI/5SGKBL?=
 =?us-ascii?Q?j2B4Y94fDUJWkYtH/paSHgPZrX43bLi0q8W+UgHPjTi5vjJ9veBhuDbNVFbK?=
 =?us-ascii?Q?UDVJGkWEMO2wjULIpN/a9TEpBHX3IXDFnpYZm5GT+llIn7J0Ao3syuYyNJ7C?=
 =?us-ascii?Q?6TdIePOanSttySufRFfiW0HBsaSy8Iu+aqTOn4VMITwBBPT05Lk9hOmEFTVl?=
 =?us-ascii?Q?gJ1OHnQSqgsZNzKVq66cwVRn+iPHN10iROIwwpEtF00vfq4AKDFA7tfuo+3y?=
 =?us-ascii?Q?CWJIZ1dKVHcv/NvuZokvgYxlt82TjtxUGXhsB1HfYVvisozavbH+AFbVBNAc?=
 =?us-ascii?Q?4pxsFdFbWP4r854CYe708VwANEKfsxh6Hnej0E2yXLF+rji3KapPbCKO3sFF?=
 =?us-ascii?Q?fJgrLcwHC2nRqSpUwcNfi9NRYiBIE9c/unQXBpY+jfTdW7VB+KJeNp1F5ADM?=
 =?us-ascii?Q?lSasIAG1rnaF903WRLZZnSd8ROXw2AGHU7GTNxTfiits97+GULGOi0x27t0t?=
 =?us-ascii?Q?hVpuj06efw3TCU6CCzha68Q5d5Cg+iXPgae25G8gi//95FAfNUbv6PwLMLcU?=
 =?us-ascii?Q?MsafTbm31ci7McPsN+u5V/P9Gc+etw6We7ZhMnOvW3sx6ezIlW4RNGg7Jjkf?=
 =?us-ascii?Q?+Pm4IZ21Dln+cz+HCspYEQv0lpm0EsCOiDQ9tDpecBb2y/i+KtRTY+HtL6wN?=
 =?us-ascii?Q?omlwVAxyu8i7mRXDc2EI4EYtaB9DdnQKTwlgo0LXeB8moEg+xASOwyq1JUdB?=
 =?us-ascii?Q?hcJ7jJQJ5M5WRh/YhXw52/wD3I9TmSZm4xV0W8KE99SfYVm/bD6wiHAZNWFN?=
 =?us-ascii?Q?4j9f4kr5v/BOiR1J7Fx8qGC6Rd0UnR3oZlvqjO3kKSWMmylmhyRCxl70oYnK?=
 =?us-ascii?Q?gKbU2yQ1+eWtcvwlro7HdkEvACFEJq3DGbcp09oxMn/vEAhKvMYLaN9Rj+zW?=
 =?us-ascii?Q?SHsMSlmKoaBaD/AfAAYkG6idBrGKHXmbgEi4X09BOKiJcQIDGEPYn3+5qcOO?=
 =?us-ascii?Q?SDC2l+FGOL0ttXf/oX5L6iyrQuYZ9WpVqhm+VFy0F0xl4p+g+/0puEFU5jbs?=
 =?us-ascii?Q?MhWxINX9z8qZd5vwFhyl/By1rKJz+BVysW+se6UO5eNKJr/adXfXKrG01nDA?=
 =?us-ascii?Q?gHGAB31ee5kt6oi60r1+CJiEp7U67NdVc5eZ6+JV8VsBc7KqmLvuMBMESR6M?=
 =?us-ascii?Q?CTLbrVgo9nNn2xv+/5xlDFSG0yx+7S8xE/M7RSTA0xefdwI/Zp7FesQ4Zq/x?=
 =?us-ascii?Q?XwKLw/m7od7cyZa+TcoxywvOU4loTV+Z7ugkF1yFyfYxUjaohguZbZ+QGxpF?=
 =?us-ascii?Q?gVK7TfQnz8+8OVg6vSA3NbSNYLlY7ZF9Tz56CpjqosCFhWDX+DKYIg=3D=3D?=
Content-Type: multipart/report;
	boundary="_000_7e14074375084f58863dd9c157223bb0uzhch_";
	report-type=disposition-notification
MIME-Version: 1.0
X-OriginatorOrg: uzh.ch
X-MS-Exchange-CrossTenant-AuthAs: Internal
X-MS-Exchange-CrossTenant-AuthSource: ZRAP278MB0737.CHEP278.PROD.OUTLOOK.COM
X-MS-Exchange-CrossTenant-Network-Message-Id: 5a4b4916-8b11-4299-6212-08dccb1ee13a
X-MS-Exchange-CrossTenant-originalarrivaltime: 02 Sep 2024 07:14:26.7778
 (UTC)
X-MS-Exchange-CrossTenant-fromentityheader: Hosted
X-MS-Exchange-CrossTenant-id: c7e438db-e462-4c22-a90a-c358b16980b3
X-MS-Exchange-CrossTenant-mailboxtype: HOSTED
X-MS-Exchange-CrossTenant-userprincipalname: l8lBMlWJvvwEJMQao8v9vJUIYKWZKSgdN7KpbjFFGNv/tIHyoLQXu+pNvyi3mI/QqE04nFPfEgPcf4H3xCB6Llf4dAivxuVpci3L5WxWF38=
X-MS-Exchange-Transport-CrossTenantHeadersStamped: ZRAP278MB0898
Status: RO
Content-Length: 2158
Lines: 60

--_000_7e14074375084f58863dd9c157223bb0uzhch_
Content-Type: multipart/alternative;
	boundary="_002_7e14074375084f58863dd9c157223bb0uzhch_"

--_002_7e14074375084f58863dd9c157223bb0uzhch_
Content-Type: text/plain; charset="us-ascii"
Content-Transfer-Encoding: quoted-printable

Ihre Nachricht

   An: TESTER 002
   Betreff: [Prime Minister's Science Prizes] You are invited as a referee =
for a Prime Minister's Science Prizes application
   Gesendet: Montag, 2. September 2024 05:57:23 (UTC+01:00) Amsterdam, Berl=
in, Bern, Rome, Stockholm, Vienna

 wurde am Montag, 2. September 2024 09:14:26 (UTC+01:00) Amsterdam, Berlin,=
 Bern, Rome, Stockholm, Vienna gelesen.

--_002_7e14074375084f58863dd9c157223bb0uzhch_
Content-Type: text/html; charset="us-ascii"
Content-Transfer-Encoding: quoted-printable

<html>
<head>
<meta http-equiv=3D"Content-Type" content=3D"text/html; charset=3Dus-ascii"=
>
<meta name=3D"Generator" content=3D"Microsoft Exchange Server">
<!-- converted from text --><style><!-- .EmailQuote { margin-left: 1pt; pad=
ding-left: 4pt; border-left: #800000 2px solid; } --></style>
</head>
<body>
<font size=3D"2"><span style=3D"font-size:11pt;">
<div class=3D"PlainText">Ihre Nachricht <br>
<br>
&nbsp;&nbsp; An: TESTER 002<br>
&nbsp;&nbsp; Betreff: [Prime Minister's Science Prizes] You are invited as =
a referee for a Prime Minister's Science Prizes application<br>
&nbsp;&nbsp; Gesendet: Montag, 2. September 2024 05:57:23 (UTC+01:00) Amste=
rdam, Berlin, Bern, Rome, Stockholm, Vienna<br>
<br>
&nbsp;wurde am Montag, 2. September 2024 09:14:26 (UTC+01:00) Amsterdam, Be=
rlin, Bern, Rome, Stockholm, Vienna gelesen.</div>
</span></font>
</body>
</html>

--_002_7e14074375084f58863dd9c157223bb0uzhch_--

--_000_7e14074375084f58863dd9c157223bb0uzhch_
Content-Type: message/disposition-notification

Final-recipient: RFC822; test001@test.ch
Disposition: automatic-action/MDN-sent-automatically; displayed
X-MSExch-Correlation-Key: ueihwHNdwUSBbyFeHPuD7Q==
Original-Message-ID: <5bBM2peNQN56hA@portal.pmscienceprizes.org.nz>
X-Display-Name: TESTER 002


--_000_7e14074375084f58863dd9c157223bb0uzhch_--

