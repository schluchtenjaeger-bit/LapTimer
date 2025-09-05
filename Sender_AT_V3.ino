// ATtiny13A (MicroCore), Clock: 9.6 MHz internal (CKDIV8 disabled)
// IR-LED  -> PB1 / OC0B (Pin 6) -> BC337 -> 33 Ω -> LED -> +5V
// CTRL-LED-> PB3 (Pin 2) -> 330 Ω -> GND
// Ziel (Pi misst FALLING->FALLING): 1500, 3500, 1500 µs

#ifndef F_CPU
#define F_CPU 9600000UL
#endif
#include <avr/io.h>
#include <util/delay.h>
#include <stdint.h>

// ---------- Ziel-Intervalle (FALLING→FALLING) ----------
static const uint16_t T_US[] = {1500u, 3500u, 1500u};
#define N_T (sizeof(T_US)/sizeof(T_US[0]))

// ---------- Start-/Frame-Pausen & Wiederholungen ----------
#define START_GAP_US  9000u   // >8000, damit dein Decoder "Neustart" erkennt
#define FRAME_GAP_US  9000u   // Lücke zwischen Frames
#define REPEATS          8    // Wie oft das 3er-Muster pro Frame gesendet wird

// ---------- MARK-Länge (kurz halten; TSOP-freundlich) ----------
#define MARK_US_BASE   300u   // reale Markdauer (Rest = SPACE bis zum Sollintervall)

// ============================================================
//                KALIBRIERUNG (Timing-Faktor)
// Dein Tiny timet ~1.8x zu langsam -> alle Zeiten * (5/9)
#define SCALE_NUM 5u
#define SCALE_DEN 9u

// Feintuning (int-taugliche "Fudge"-Faktoren):
// Kurz-Intervall (3000 µs) ~ +14 %
#define FUDGE_SHORT_NUM 130u
#define FUDGE_SHORT_DEN 125u   // = 1.04

// Lang-Intervall  (4500 µs) ~ +9 %
#define FUDGE_LONG_NUM   79u
#define FUDGE_LONG_DEN   75u   // = 1.093

// ============================================================

// -------- 38 kHz PWM auf OC0B (PB1), ~33 % Duty --------
static inline void pwm38k_init() {
  DDRB |= _BV(PB1); // OC0B out
  uint16_t top  = (F_CPU / 38000ul) - 1; if (top > 255) top = 255;        // ~252
  uint16_t ocrb = ((top + 1) / 3) - 1;   if (ocrb > top)  ocrb = top / 3; // ~83
  TCCR0A = 0; TCCR0B = 0;
  TCCR0A |= _BV(WGM00) | _BV(WGM01);  // Fast PWM
  TCCR0B |= _BV(WGM02);               // Mode 7 (OCR0A = TOP)
  TCCR0A |= _BV(COM0B1);              // non-inverting auf OC0B
  OCR0A = (uint8_t)top;
  OCR0B = (uint8_t)ocrb;
  TCCR0B |= _BV(CS00);                // Prescaler 1
}

static inline void carrier_on()  { TCCR0A |=  _BV(COM0B1); }
static inline void carrier_off() { TCCR0A &= ~_BV(COM0B1); PORTB &= ~_BV(PB1); }

// -------- kleine Hilfen --------
static inline void dly_us(unsigned us){ while (us--) _delay_us(1); }

static inline uint16_t scale_base(uint16_t us) {
  return (uint16_t)((uint32_t)us * SCALE_NUM / SCALE_DEN);
}
static inline uint16_t scale_short(uint16_t us) {
  return (uint16_t)((uint32_t)scale_base(us) * FUDGE_SHORT_NUM / FUDGE_SHORT_DEN);
}
static inline uint16_t scale_long(uint16_t us) {
  return (uint16_t)((uint32_t)scale_base(us) * FUDGE_LONG_NUM / FUDGE_LONG_DEN);
}

// Sende genau EIN FALLING→FALLING-Intervall T:
// 1) starte MARK (Falling#i), halte MARK (skaliert), 2) SPACE bis exakt T (skaliert)
static inline void send_interval_F2F(uint16_t T, uint8_t is_long) {
  // skaliere Zielintervall & MARK
  const uint16_t Tscaled   = is_long ? scale_long(T) : scale_short(T);
  const uint16_t markScaled= scale_short(MARK_US_BASE);
  uint16_t spaceScaled = (Tscaled > markScaled) ? (uint16_t)(Tscaled - markScaled) : 20u;

  // MARK
  carrier_on();
  dly_us(markScaled);
  carrier_off();

  // SPACE bis zur nächsten Falling
  dly_us(spaceScaled);
}

int main(void){
  pwm38k_init(); carrier_off();

  // CTRL-LED (PB3)
  DDRB |= _BV(PB3);
  PORTB &= ~_BV(PB3);

  for(;;){
    // reine Startlücke (skaliert), damit dein Decoder "neu" beginnt (diff > 8000)
    dly_us(scale_short(START_GAP_US));

    PORTB |= _BV(PB3);
    for(uint8_t r=0; r<REPEATS; r++){
      // Reihenfolge: kurz (1500), lang (3500), kurz (1500)
      send_interval_F2F(3000u, 0);
      send_interval_F2F(4500u, 1);
      send_interval_F2F(3000u, 0);
    }
    PORTB &= ~_BV(PB3);

    // große Lücke vor dem nächsten Frame (skaliert)
    dly_us(scale_short(FRAME_GAP_US));
  }
} 
