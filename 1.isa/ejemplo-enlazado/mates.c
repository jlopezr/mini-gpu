/* Biblioteca en C que el programa no usa: al enlazar con libejemplo.a, vlink no la mete. */
int cuadrado(int x)
{
    return x * x;
}

int cubo(int x)
{
    return cuadrado(x) * x;
}
