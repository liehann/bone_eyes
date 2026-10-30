"""Prototype wiring check for the proposed ESP32 position (docs/skull-v2-architecture.md).

ESP32-DevKitC-VIE lies flat, pins down, long axis along X, pin 1 (antenna
end) toward +X (the skull's left, the L eye), USB at -X. J3 is the front
row (toward the eye bar), J2 the back row. Leads are modelled as: a straight
run out of each connector, then a direct path times a routing factor.
Prints a markdown table for the doc. The lengths are estimates; the build's
cable router replaces this.
"""
import numpy as np

# DevKitC v4 headers, pin 1 at the antenna end
J2 = ['3V3', 'EN', '36', '39', '34', '35', '32', '33', '25', '26', '27', '14', '12', 'GND', '13', 'D2', 'D3', 'CMD', '5V']
J3 = ['GND', '23', '22', 'TX', 'RX', '21', 'GND', '19', '18', '5', '17', '16', '4', '0', '2', '15', 'D1', 'D0', 'CLK']

ESP = dict(xc=0.0, yc=47.4, zb=22.0, row=11.43, pitch=2.54)   # PCB bottom z; rows at yc -+ row
HOUSING = 14.0      # DuPont female housing length (rigid)
SH = 4.0            # SH1.0 plug at the module (rigid)
ROUTE = 1.15        # routing factor on the direct path (bends, going round the housings)
LEAD = 100.0        # LCD lead, pin to pin (user: "about 10 cm")


def pin_xyz(header, p):
    x = ESP['xc'] + 22.86 - (p - 1) * ESP['pitch']
    y = ESP['yc'] + (-ESP['row'] if header == 'J3' else ESP['row'])
    z = ESP['zb'] - 2.5 - HOUSING          # wire leaves the bottom of the DuPont housing
    return np.array([x, y, z])


def find(pin):
    for h, L in (('J2', J2), ('J3', J3)):
        if pin in L:
            return h, L.index(pin) + 1
    raise KeyError(pin)


LEADS = {   # lead: (start point = where the wire leaves the connector, straight run, {signal: (header, pin)})
    'LCD L (skull left, +X)': (np.array([22.3, 26.85, 0.0]), 8.0,
                               dict(SCLK=('J3', 9), MOSI=('J3', 2), CS=('J3', 10), DC=('J3', 8), RST=('J3', 13),
                                    BL=('J3', 6), GND=('J3', 1), VCC=('J2', 1))),
    'LCD R (skull right, -X)': (np.array([-22.3, 26.85, 0.0]), 8.0,
                                dict(SCLK=('J2', 12), MOSI=('J2', 15), CS=('J3', 16), DC=('J3', 3), RST=('J2', 9),
                                     BL=('J2', 10), GND=('J2', 14), VCC=('J2', 19))),
}

if __name__ == '__main__':
    free = LEAD - HOUSING - SH
    print('LCD lead %.0f mm pin to pin -> %.0f mm of free wire (housings %.0f + %.0f)' % (LEAD, free, HOUSING, SH))
    print()
    print('| Lead | Signal | ESP32 pin | Route (mm) | Slack (mm) |')
    print('|---|---|---|---|---|')
    worst = {}
    for name, (s, run, sig) in LEADS.items():
        a = s + np.array([0, run, 0])
        for k, (h, p) in sig.items():
            b = pin_xyz(h, p)
            L = run + 5.0 + ROUTE * np.linalg.norm(b - a)
            lab = (J2 if h == 'J2' else J3)[p - 1]
            print('| %s | %s | %s pin %d (GPIO %s) | %.0f | %.0f |' % (name, k, h, p, lab, L, free - L))
            worst[name] = max(worst.get(name, 0), L)
    print()
    for k, v in worst.items():
        print('%s: longest route %.0f mm, least slack %.0f mm' % (k, v, free - v))
    # servo and radar (lengths unknown)
    servo = np.array([15.0, 72.0, -36.0]); r = pin_xyz('J2', 11)
    print('servo lead to J2 pin 11 (GPIO27): ~%.0f mm' % (10 + ROUTE * np.linalg.norm(r - servo)))
    radar = np.array([0.0, 8.0, -27.5])
    for p in (5, 7, 8):
        print('radar lead to J2 pin %d (GPIO %s): ~%.0f mm installed' % (p, J2[p - 1], 10 + ROUTE * np.linalg.norm(pin_xyz('J2', p) - radar)))
